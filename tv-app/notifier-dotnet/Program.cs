using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using Tizen;
using Tizen.Applications;
using Tizen.Applications.Notifications;
using Tizen.NUI;
using Tizen.NUI.BaseComponents;

namespace Notifier
{
    // Samstream notifier (Tizen.NET). A backgrounded instance's
    // NotificationManager.Post overlays any foreground app silently (confirmed).
    // A LAN HTTP listener on :8181 lets Home Assistant trigger a notification by
    // posting straight to the TV — fully local, no web-app hop, no takeover.
    //
    // Only Home Assistant may post. Every request is authenticated with an
    // HMAC-SHA256 signature over its fields, using a per-TV shared secret that
    // HA writes into the package at install (res/shared.key). A timestamp and a
    // single-use nonce stop replay. A request that is missing, stale, replayed
    // or wrongly signed is rejected with 401 before any work (fail closed: with
    // no key file loaded, every post is refused).
    //   GET http://<tv-ip>:8181/notify?title=..&content=..&icon=..&image=..&ts=..&nonce=..&sig=..
    //   sig = hex(HMAC_SHA256(secret, ts\nnonce\ntitle\ncontent\nicon\nimage))
    // icon = a bundled icon name (res/icons/<icon>.png); image = an http(s) URL
    // the notifier downloads for the larger thumbnail. Both are covered by the
    // signature, so no one can tamper with them on a valid request.
    // GET /health answers "ok" without auth, so HA can see the app is resident.
    //
    // The same listener drives the corner camera (CornerCamera.cs), signed the
    // same way, over these fields:
    //   POST /camera?corner=&size=&seconds=&url=&title=&message=&text_position=
    //        &text_size=&ts=&nonce=&sig=
    //        ts, nonce, "camera", corner, size, seconds, url, title, message,
    //        text_position, text_size
    //   POST /camera/message?message=..   ts, nonce, "camera/message", message
    //   POST /camera/close?..             ts, nonce, "camera/close"
    //
    // The HTTP thread only enqueues; a main-loop timer dequeues and acts, so
    // NotificationManager.Post and all drawing run on the app's main thread.
    //
    // The app's window is always transparent and never takes the remote: it is
    // invisible until a camera is shown.
    internal sealed class Program : NUIApplication
    {
        private const string Tag = "SAMSTREAM_NOTI";
        private const int Port = 8181;
        // How far a request's timestamp may be from now, in seconds (clock skew
        // + flight time); older or future-dated requests are refused.
        private const long SkewSeconds = 30;

        private readonly ConcurrentQueue<(string title, string content, string icon, string image)> _queue =
            new ConcurrentQueue<(string title, string content, string icon, string image)>();
        private static readonly HttpClient Http = new HttpClient
        {
            Timeout = TimeSpan.FromSeconds(6),
        };
        // Nonces seen inside the skew window, so a captured request can't replay.
        private readonly Dictionary<string, long> _seen = new Dictionary<string, long>();
        private readonly object _seenLock = new object();
        private byte[] _key;
        private Tizen.NUI.Timer _drainTimer;
        private readonly CornerCamera _camera = new CornerCamera();
        private readonly ConcurrentQueue<Action> _actions = new ConcurrentQueue<Action>();

        protected override void OnCreate()
        {
            base.OnCreate();
            _key = LoadKey();
            CornerCamera.PrepareWindow();

            StartServer();

            // Drain the queues on the main loop (Post and NUI need that thread).
            // The Timer MUST be a retained field: a local gets GC'd and silently
            // stops ticking (proven — "HTTP 200 but no notification").
            _drainTimer = new Tizen.NUI.Timer(200);
            _drainTimer.Tick += (s, e) =>
            {
                while (_queue.TryDequeue(out var item))
                {
                    Post(item.title, item.content, item.icon, item.image);
                }
                while (_actions.TryDequeue(out var action))
                {
                    try { action(); }
                    catch (Exception ex)
                    {
                        Log.Error(Tag, "ACTION_FAIL " + ex.GetType().Name + ": " + ex.Message);
                    }
                }
                return true;
            };
            _drainTimer.Start();

        }

        // Samstream (the web app) launches us as it starts, which brings this app
        // to the front: raise Samstream straight back so it stays the app on
        // screen. Home Assistant can also start us (no secret in the launch), and
        // then whatever is on screen is left alone. This does not loop: Samstream
        // starts us only from its own first boot.
        private const string SamstreamAppId = "SmStrm0001.Samstream";

        private void RaiseSamstream()
        {
            try
            {
                var raise = new AppControl
                {
                    ApplicationId = SamstreamAppId,
                    Operation = AppControlOperations.Default,
                };
                AppControl.SendLaunchRequest(raise);
            }
            catch (Exception ex)
            {
                Log.Error(Tag, "RAISE_FAIL " + ex.GetType().Name + ": " + ex.Message);
            }
        }

        // Read the per-TV shared secret HA stamps into the package at install.
        // Missing/empty key -> null -> the listener refuses every post.
        private static byte[] LoadKey()
        {
            try
            {
                string res = Application.Current?.DirectoryInfo?.Resource;
                if (string.IsNullOrEmpty(res))
                {
                    return null;
                }
                string path = System.IO.Path.Combine(res, "shared.key");
                if (!File.Exists(path))
                {
                    return null;
                }
                string text = File.ReadAllText(path).Trim();
                return text.Length == 0 ? null : Encoding.UTF8.GetBytes(text);
            }
            catch (Exception ex)
            {
                Log.Error(Tag, "KEY_FAIL " + ex.GetType().Name + ": " + ex.Message);
                return null;
            }
        }

        private void StartServer()
        {
            var thread = new Thread(() =>
            {
                try
                {
                    var http = new HttpListener();
                    http.Prefixes.Add("http://*:" + Port + "/");
                    http.Start();
                    Log.Error(Tag, "LISTENING " + Port);
                    while (true)
                    {
                        HttpListenerContext ctx = http.GetContext();
                        try
                        {
                            Handle(ctx);
                        }
                        catch (Exception ex)
                        {
                            Log.Error(Tag, "REQ_FAIL " + ex.GetType().Name + ": " + ex.Message);
                            TryRespond(ctx, 500, "error");
                        }
                    }
                }
                catch (Exception ex)
                {
                    Log.Error(Tag, "SRV_FAIL " + ex.GetType().FullName + ": " + ex.Message);
                }
            }) { IsBackground = true };
            thread.Start();
        }

        private void Handle(HttpListenerContext ctx)
        {
            string path = ctx.Request.Url?.AbsolutePath ?? "/";
            // Liveness probe for HA's resident-check. No secret, no state.
            if (path == "/health")
            {
                TryRespond(ctx, 200, "ok");
                return;
            }

            var q = ctx.Request.QueryString;
            if (path.StartsWith("/camera", StringComparison.Ordinal))
            {
                HandleCamera(ctx, path);
                return;
            }
            string title = q["title"] ?? "Samstream";
            string content = q["content"] ?? string.Empty;
            string icon = q["icon"] ?? string.Empty;
            string image = q["image"] ?? string.Empty;
            string ts = q["ts"];
            string nonce = q["nonce"];
            string sig = q["sig"];

            if (!Authorized(ts, nonce, sig, title, content, icon, image))
            {
                Log.Error(Tag, "UNAUTHORIZED");
                TryRespond(ctx, 401, "unauthorized");
                return;
            }

            if (string.IsNullOrEmpty(title))
            {
                title = "Samstream";
            }
            _queue.Enqueue((title, content, icon, image));
            TryRespond(ctx, 200, "{\"ok\":true}");
        }

        // Corner camera requests: state changes, so POST only.
        private void HandleCamera(HttpListenerContext ctx, string path)
        {
            if (ctx.Request.HttpMethod != "POST")
            {
                TryRespond(ctx, 405, "method not allowed");
                return;
            }
            var q = ctx.Request.QueryString;
            string corner = q["corner"] ?? string.Empty;
            string size = q["size"] ?? string.Empty;
            string seconds = q["seconds"] ?? string.Empty;
            string url = q["url"] ?? string.Empty;
            string title = q["title"] ?? string.Empty;
            string message = q["message"] ?? string.Empty;
            string textPosition = q["text_position"] ?? string.Empty;
            string textSize = q["text_size"] ?? string.Empty;
            string[] fields =
                path == "/camera" ? new[]
                {
                    "camera", corner, size, seconds, url, title, message, textPosition, textSize,
                }
                : path == "/camera/message" ? new[] { "camera/message", message }
                : path == "/camera/close" ? new[] { "camera/close" }
                : null;
            if (fields == null)
            {
                TryRespond(ctx, 404, "not found");
                return;
            }
            if (!Authorized(q["ts"], q["nonce"], q["sig"], fields))
            {
                Log.Error(Tag, "UNAUTHORIZED");
                TryRespond(ctx, 401, "unauthorized");
                return;
            }
            if (path == "/camera")
            {
                if (!CornerCamera.KnownCorner(corner) || !CornerCamera.KnownSize(size) ||
                    !int.TryParse(seconds, out int hold) || hold < 1 || hold > 3600 ||
                    !CornerCamera.KnownTextPosition(textPosition) ||
                    !CornerCamera.KnownTextSize(textSize) || !IsHttp(url))
                {
                    TryRespond(ctx, 400, "bad request");
                    return;
                }
                _actions.Enqueue(() => _camera.Show(
                    corner, size, hold, url, title, message, textPosition, textSize));
            }
            else if (path == "/camera/message")
            {
                _actions.Enqueue(() => _camera.SetMessage(message));
            }
            else
            {
                _actions.Enqueue(() => _camera.Close());
            }
            TryRespond(ctx, 200, "{\"ok\":true}");
        }

        private static bool IsHttp(string url) =>
            url.StartsWith("http://", StringComparison.Ordinal) ||
            url.StartsWith("https://", StringComparison.Ordinal);

        // True only for a fresh, correctly signed request from HA. The signature
        // covers ts, nonce and then `fields`, joined by newlines.
        private bool Authorized(string ts, string nonce, string sig, params string[] fields)
        {
            if (_key == null)
            {
                return false; // fail closed: no key installed
            }
            if (string.IsNullOrEmpty(ts) || string.IsNullOrEmpty(nonce) ||
                string.IsNullOrEmpty(sig))
            {
                return false;
            }
            if (!long.TryParse(ts, out long when))
            {
                return false;
            }
            long now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
            if (Math.Abs(now - when) > SkewSeconds)
            {
                return false; // stale or future-dated
            }

            string message = ts + "\n" + nonce + "\n" + string.Join("\n", fields);
            byte[] expected;
            using (var mac = new HMACSHA256(_key))
            {
                expected = mac.ComputeHash(Encoding.UTF8.GetBytes(message));
            }
            byte[] given = FromHex(sig);
            if (given == null || !FixedTimeEquals(expected, given))
            {
                return false;
            }
            // Signature is valid and fresh — accept this nonce exactly once.
            return RememberNonce(nonce, now);
        }

        // Record the nonce; false if it was already used inside the window.
        // Also prunes nonces older than the skew window so the set stays small.
        private bool RememberNonce(string nonce, long now)
        {
            lock (_seenLock)
            {
                var stale = new List<string>();
                foreach (var kv in _seen)
                {
                    if (now - kv.Value > SkewSeconds)
                    {
                        stale.Add(kv.Key);
                    }
                }
                foreach (var k in stale)
                {
                    _seen.Remove(k);
                }
                if (_seen.ContainsKey(nonce))
                {
                    return false; // replay
                }
                _seen[nonce] = now;
                return true;
            }
        }

        private static byte[] FromHex(string hex)
        {
            if (hex == null || (hex.Length & 1) == 1)
            {
                return null;
            }
            var bytes = new byte[hex.Length / 2];
            for (int i = 0; i < bytes.Length; i++)
            {
                int hi = HexVal(hex[i * 2]);
                int lo = HexVal(hex[i * 2 + 1]);
                if (hi < 0 || lo < 0)
                {
                    return null;
                }
                bytes[i] = (byte)((hi << 4) | lo);
            }
            return bytes;
        }

        private static int HexVal(char c)
        {
            if (c >= '0' && c <= '9') return c - '0';
            if (c >= 'a' && c <= 'f') return c - 'a' + 10;
            if (c >= 'A' && c <= 'F') return c - 'A' + 10;
            return -1;
        }

        // Constant-time compare (HMACSHA256 is always 32 bytes; no early exit).
        private static bool FixedTimeEquals(byte[] a, byte[] b)
        {
            if (a.Length != b.Length)
            {
                return false;
            }
            int diff = 0;
            for (int i = 0; i < a.Length; i++)
            {
                diff |= a[i] ^ b[i];
            }
            return diff == 0;
        }

        private static void TryRespond(HttpListenerContext ctx, int status, string body)
        {
            try
            {
                byte[] buf = Encoding.UTF8.GetBytes(body);
                ctx.Response.StatusCode = status;
                ctx.Response.OutputStream.Write(buf, 0, buf.Length);
                ctx.Response.Close();
            }
            catch (Exception ex)
            {
                Log.Error(Tag, "RESP_FAIL " + ex.GetType().Name + ": " + ex.Message);
            }
        }

        // The Samstream web app (the UI half of the same hybrid package) talks to
        // the notifier over local app-control — not a LAN surface, so it carries no
        // signature. It does two things:
        //   - hands over the per-TV secret (key "samstream_secret") when it starts
        //     the notifier, so the LAN HTTP listener can authenticate HA even when
        //     no key file was stamped into the package;
        //   - may post a notification directly (keys "title"/"content"), no network.
        protected override void OnAppControlReceived(AppControlReceivedEventArgs e)
        {
            base.OnAppControlReceived(e);
            var extra = e.ReceivedAppControl?.ExtraData;
            if (extra == null)
            {
                return;
            }
            if (extra.TryGet("samstream_secret", out string s) && !string.IsNullOrEmpty(s))
            {
                _key = Encoding.UTF8.GetBytes(s.Trim());
            }
            if (extra.TryGet("title", out string t) && !string.IsNullOrEmpty(t))
            {
                extra.TryGet("content", out string c);
                _queue.Enqueue((t, c ?? string.Empty, string.Empty, string.Empty));
            }
            if (!string.IsNullOrEmpty(s))
            {
                RaiseSamstream();
            }
        }

        private static void Post(string title, string content, string icon, string image)
        {
            try
            {
                var noti = new Notification { Title = title, Content = content };
                // The TV corner toast renders Notification.Icon. Prefer a
                // downloaded image (e.g. a camera snapshot) HA chose, else a
                // bundled icon by name, else the Samstream brand icon.
                string iconPath = DownloadImage(image) ?? ResolveIcon(icon);
                if (iconPath != null)
                {
                    noti.Icon = iconPath;
                }
                NotificationManager.Post(noti);
                Log.Error(Tag, "POST_OK " + title);
            }
            catch (Exception ex)
            {
                Log.Error(Tag, "POST_FAIL " + ex.GetType().FullName + ": " + ex.Message);
            }
        }

        // Map an icon name to a bundled file (res/icons/<name>.png), defaulting to
        // the Samstream brand icon. Unknown/malformed names fall back to the brand.
        private static string ResolveIcon(string name)
        {
            try
            {
                string res = Application.Current?.DirectoryInfo?.Resource;
                if (string.IsNullOrEmpty(res))
                {
                    return null;
                }
                // Keep it a bare file name — never a path that could escape res/.
                string safe = string.IsNullOrEmpty(name) ? "samstream" : name;
                if (safe.IndexOfAny(new[] { '/', '\\', '.', ':' }) >= 0)
                {
                    safe = "samstream";
                }
                string path = System.IO.Path.Combine(res, "icons", safe + ".png");
                if (!File.Exists(path))
                {
                    path = System.IO.Path.Combine(res, "icons", "samstream.png");
                }
                return File.Exists(path) ? path : null;
            }
            catch (Exception ex)
            {
                Log.Error(Tag, "ICON_FAIL " + ex.Message);
                return null;
            }
        }

        // Download an http(s) image (e.g. a camera snapshot) to the app's data dir
        // and return its path for the notification thumbnail. The URL is part of the
        // signed request, so only HA can choose it. Any failure -> no thumbnail.
        private static string DownloadImage(string url)
        {
            if (string.IsNullOrEmpty(url) ||
                !(url.StartsWith("http://") || url.StartsWith("https://")))
            {
                return null;
            }
            try
            {
                string data = Application.Current?.DirectoryInfo?.Data;
                if (string.IsNullOrEmpty(data))
                {
                    return null;
                }
                byte[] bytes = Http.GetByteArrayAsync(url).GetAwaiter().GetResult();
                // One slot, overwritten each time — notifications are transient.
                string path = System.IO.Path.Combine(data, "noti-image");
                File.WriteAllBytes(path, bytes);
                return path;
            }
            catch (Exception ex)
            {
                Log.Error(Tag, "IMAGE_FAIL " + ex.GetType().Name + ": " + ex.Message);
                return null;
            }
        }

        private static void Main(string[] args)
        {
            var app = new Program();
            app.Run(args);
        }
    }
}
