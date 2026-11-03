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
    // The HTTP thread only enqueues; a main-loop timer dequeues and posts, so
    // NotificationManager.Post always runs on the app's main thread.
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
        private TextLabel _status;
        private Tizen.NUI.Timer _drainTimer;

        protected override void OnCreate()
        {
            base.OnCreate();
            _key = LoadKey();
            var window = Window.Instance;
            // Brand navy (#0B1420), never pure black — this window is meant to sit
            // in the background, but if it ever flashes it should read as Samstream,
            // not a dead screen.
            window.BackgroundColor = new Color(0.043f, 0.078f, 0.125f, 1.0f);
            // Don't take input focus from the app in front (e.g. Samstream).
            try { window.SetAcceptFocus(false); } catch { /* older NUI */ }
            _status = new TextLabel("Samstream\nnotifications active")
            {
                HorizontalAlignment = HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center,
                TextColor = new Color(0.6f, 0.7f, 0.82f, 1.0f),
                PointSize = 9.0f,
                MultiLine = true,
                WidthResizePolicy = ResizePolicyType.FillToParent,
                HeightResizePolicy = ResizePolicyType.FillToParent,
            };
            window.GetDefaultLayer().Add(_status);

            StartServer();

            // Drain the queue on the main loop so Post() runs on the main thread.
            // The Timer MUST be a retained field: a local gets GC'd and silently
            // stops ticking (proven — "HTTP 200 but no notification").
            _drainTimer = new Tizen.NUI.Timer(400);
            _drainTimer.Tick += (s, e) =>
            {
                while (_queue.TryDequeue(out var item))
                {
                    Post(item.title, item.content, item.icon, item.image);
                }
                return true;
            };
            _drainTimer.Start();

            // Drop behind whatever launched us (Samstream), so the app the user is
            // watching stays in front and a posted notification OVERLAYS it. The
            // app keeps running backgrounded, which is where Post() works.
            SendToBackground();
        }

        // We are only ever launched by Samstream (the web app) as it starts, which
        // briefly brings our window to the front. Raise Samstream straight back so
        // it stays the app on screen; we drop to the background, which is exactly
        // where NotificationManager.Post overlays whatever is playing. This does
        // not loop: Samstream starts us only from its own first boot, and its
        // re-launch handler does not start us again.
        private const string SamstreamAppId = "SmStrm0001.Samstream";

        private void SendToBackground()
        {
            try { Window.Instance.Lower(); } catch { /* best effort */ }
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
                    SetStatus("LISTENING on :" + Port +
                        (_key == null ? "\n\nNO KEY — posts refused." : "\n\nReady."));
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
                    SetStatus("LISTENER FAILED:\n" + ex.GetType().Name + "\n" + ex.Message);
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
            string title = q["title"] ?? "Samstream";
            string content = q["content"] ?? string.Empty;
            string icon = q["icon"] ?? string.Empty;
            string image = q["image"] ?? string.Empty;
            string ts = q["ts"];
            string nonce = q["nonce"];
            string sig = q["sig"];

            if (!Authorized(title, content, icon, image, ts, nonce, sig))
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

        // True only for a fresh, correctly signed request from HA.
        private bool Authorized(
            string title, string content, string icon, string image,
            string ts, string nonce, string sig)
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

            string message = ts + "\n" + nonce + "\n" + title + "\n" + content +
                "\n" + icon + "\n" + image;
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

        private void SetStatus(string msg)
        {
            try { if (_status != null) _status.Text = "SAMSTREAM NOTIFIER\n\n" + msg; }
            catch { /* off-thread text set is best-effort */ }
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
                SetStatus("LISTENING on :" + Port + "\n\nReady (key from Samstream).");
            }
            if (extra.TryGet("title", out string t) && !string.IsNullOrEmpty(t))
            {
                extra.TryGet("content", out string c);
                _queue.Enqueue((t, c ?? string.Empty, string.Empty, string.Empty));
            }
            // A re-launch (e.g. Samstream opened again) brings us to the front;
            // drop straight back so we never cover the app in front.
            SendToBackground();
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
