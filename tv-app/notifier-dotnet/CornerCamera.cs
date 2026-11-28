using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Net.Http;
using System.Reflection;
using System.Text;
using System.Threading;
using Tizen;
using Tizen.Applications;
using Tizen.NUI;
using Tizen.NUI.BaseComponents;
using Timer = Tizen.NUI.Timer;

namespace Notifier
{
    // A live camera in a corner of the screen, over whatever is playing. Each
    // box gets its own transparent, non-focusable Notification window, destroyed
    // with it: the video underneath keeps playing and the remote keeps
    // controlling it. The app's own window stays behind everything.
    // Pictures come from Home Assistant as MJPEG and are drawn as images, because
    // the TV's video decoder belongs to the app underneath.
    // Every method here runs on the main thread, except Fetch.
    // The window handling (a transparent Notification window per box, the app's
    // own window lowered) is adapted from busycursor/tizen-notifier,
    // MIT, Copyright (c) 2026 busycursor: see
    // custom_components/samstream/bundled/THIRD-PARTY-NOTICES.md.
    internal sealed class CornerCamera
    {
        private const string Tag = "SAMSTREAM_NOTI";
        private const int ScreenWidth = 1920;
        private const int ScreenHeight = 1080;
        private const int Margin = 32; // frame image around the picture
        private const int Edge = 20; // from the screen edge to the frame image
        private const int MaxFrameBytes = 2 * 1024 * 1024;

        // Must match scripts/make_pip_frames.py.
        private static readonly Dictionary<string, Size2D> Sizes = new Dictionary<string, Size2D>
        {
            { "small", new Size2D(480, 270) },
            { "medium", new Size2D(640, 360) },
            { "large", new Size2D(880, 495) },
        };

        // Caption text as a share of the default size.
        private static readonly Dictionary<string, float> TextSizes = new Dictionary<string, float>
        {
            { "normal", 1.0f },
            { "large", 1.15f },
            { "extra_large", 1.3f },
        };

        private static readonly HttpClient Http = new HttpClient
        {
            Timeout = Timeout.InfiniteTimeSpan, // the stream stays open
        };

        private readonly ConcurrentQueue<string> _frames = new ConcurrentQueue<string>();
        private readonly List<ImageView> _pictures = new List<ImageView>();
        private Window _window;
        private View _box;
        private View _video;
        private View _caption;
        private TextLabel _title;
        private TextLabel _message;
        private Size2D _size;
        private float _textScale;
        private bool _textOnTop;
        private CancellationTokenSource _stop;
        // Timers stay referenced or they are collected and stop ticking.
        private Timer _draw;
        private Timer _close;
        private Timer _place;
        private int _run;

        public static bool KnownSize(string size) => Sizes.ContainsKey(size);

        public static bool KnownTextSize(string size) => TextSizes.ContainsKey(size);

        public static bool KnownTextPosition(string position) =>
            position == "bottom" || position == "middle" || position == "top";

        public static bool KnownCorner(string corner) =>
            corner == "top_left" || corner == "top_right" ||
            corner == "bottom_left" || corner == "bottom_right";

        // Keep the app's own window invisible, without the remote, and behind
        // every app. Left in front, the TV counts this app as the one on screen
        // when Samstream wakes it, and Home Assistant cannot return to what was
        // playing. Hiding it instead would close the app.
        public static void StayBehind()
        {
            var window = Window.Instance;
            Try("main", () =>
            {
                window.BackgroundColor = Color.Transparent;
                window.SetTransparency(true);
                window.SetAcceptFocus(false);
                window.WindowSize = new Size2D(1, 1);
                window.WindowPosition = new Position2D(0, 0);
                window.Lower();
            });
        }

        public void Show(
            string corner, string size, int seconds, string url, string title, string message,
            string textPosition, string textSize)
        {
            Close();
            _size = Sizes[size];
            _textScale = TextSizes[textSize];
            // A small box has no useful middle: the caption is at the top or bottom.
            _textOnTop = textPosition == "top";
            int width = _size.Width + 2 * Margin;
            int height = _size.Height + 2 * Margin;
            int x = corner.EndsWith("right") ? ScreenWidth - Edge - width : Edge;
            int y = corner.StartsWith("bottom") ? ScreenHeight - Edge - height : Edge;

            _box = new View { Size2D = new Size2D(width, height) };
            _video = new View
            {
                Size2D = _size,
                Position2D = new Position2D(Margin, Margin),
                BackgroundColor = new Color(0.043f, 0.078f, 0.125f, 1.0f),
            };
            _box.Add(_video);
            BuildCaption();
            string res = Application.Current.DirectoryInfo.Resource;
            _box.Add(new ImageView
            {
                Size2D = new Size2D(width, height),
                ResourceUrl = System.IO.Path.Combine(res, "frames", size + ".png"),
            });
            SetText(title, message);

            var own = NewWindow(x, y, width, height);
            if (own != null)
            {
                ShowInOwnWindow(own, x, y, width, height);
            }
            else
            {
                ShowInMainWindow(x, y);
            }

            _stop = new CancellationTokenSource();
            var token = _stop.Token;
            int run = ++_run;
            new Thread(() => Fetch(url, run, token)) { IsBackground = true }.Start();
            _draw = new Timer(40);
            _draw.Tick += (s, e) =>
            {
                Draw();
                return true;
            };
            _draw.Start();
            _close = new Timer((uint)seconds * 1000);
            _close.Tick += (s, e) =>
            {
                Close();
                return false;
            };
            _close.Start();
        }

        private void ShowInOwnWindow(Window window, int x, int y, int width, int height)
        {
            _window = window;
            window.GetDefaultLayer().Add(_box);
            Try("show", () => window.Show());
            // The compositor can ignore a size set before the window is up: set
            // it again once it is.
            PlaceLater(window, () =>
            {
                window.WindowSize = new Size2D(width, height);
                window.WindowPosition = new Position2D(x, y);
            });
        }

        // Older TVs have the app's window only: the box is placed inside it, and
        // the window covers the screen while the box is up.
        private void ShowInMainWindow(int x, int y)
        {
            var window = Window.Instance;
            _window = window;
            _box.Position2D = new Position2D(x, y);
            window.GetDefaultLayer().Add(_box);
            MakeNotification(window);
            Try("show", () => window.Show());
            // As above: shrink, then grow, once it is up.
            Grow(window);
            PlaceLater(window, () =>
            {
                Idle(window);
                Grow(window);
            });
        }

        private void PlaceLater(Window window, Action place)
        {
            _place = new Timer(500);
            _place.Tick += (s, e) =>
            {
                if (_window == window)
                {
                    Try("place", place);
                }
                return false;
            };
            _place.Start();
        }

        // New text for the camera on screen; nothing happens without one.
        public void SetMessage(string message)
        {
            if (_box != null)
            {
                SetText(_title.Text, message);
            }
        }

        public void Close()
        {
            _stop?.Cancel();
            _stop = null;
            _draw?.Stop();
            _close?.Stop();
            _place?.Stop();
            while (_frames.TryDequeue(out var path))
            {
                Delete(path);
            }
            foreach (var picture in _pictures)
            {
                var file = picture.ResourceUrl;
                _video.Remove(picture);
                picture.Dispose();
                Delete(file);
            }
            _pictures.Clear();
            if (_box == null)
            {
                return;
            }
            var window = _window;
            _window = null;
            window?.GetDefaultLayer().Remove(_box);
            _box.Dispose();
            _box = null;
            if (window != null && window != Window.Instance)
            {
                Try("hide", () => window.Hide());
                Try("dispose", () => window.Dispose());
            }
            StayBehind();
        }

        // A second window needs a constructor the Tizen 4 build target does not
        // declare, so look for it on the TV. Null where there is none.
        private static Window NewWindow(int x, int y, int width, int height)
        {
            try
            {
                var ctor = typeof(Window).GetConstructor(
                    BindingFlags.Instance | BindingFlags.Public, null,
                    new[] { typeof(string), typeof(Rectangle), typeof(bool) }, null);
                if (ctor == null)
                {
                    return null;
                }
                var window = (Window)ctor.Invoke(new object[]
                {
                    "samstream-corner", new Rectangle(x, y, width, height), true,
                });
                Configure(window);
                return window;
            }
            catch (Exception ex)
            {
                Log.Error(Tag, "CORNER_window " + ex.GetType().Name + ": " + ex.Message);
                return null;
            }
        }

        private static void MakeNotification(Window window)
        {
            Try("type", () => window.Type = WindowType.Notification);
            Try("level", () => window.SetNotificationLevel(NotificationLevel.High));
        }

        private static void Configure(Window window)
        {
            MakeNotification(window);
            Try("transparent", () =>
            {
                window.BackgroundColor = Color.Transparent;
                window.SetTransparency(true);
            });
            Try("opaque", () => window.SetOpaqueState(false));
            Try("focus", () => window.SetAcceptFocus(false));
        }

        private static void Idle(Window window) => Try("idle", () =>
        {
            window.WindowSize = new Size2D(1, 1);
            window.WindowPosition = new Position2D(0, 0);
        });

        private static void Grow(Window window) => Try("grow", () =>
        {
            window.WindowPosition = new Position2D(0, 0);
            window.WindowSize = new Size2D(ScreenWidth, ScreenHeight);
        });

        private void BuildCaption()
        {
            _caption = new View
            {
                BackgroundColor = new Color(0.043f, 0.078f, 0.125f, 0.72f),
            };
            _title = Label(new Color(0.72f, 0.77f, 0.83f, 1.0f));
            _message = Label(Color.White);
            _caption.Add(_title);
            _caption.Add(_message);
            _box.Add(_caption);
        }

        private static TextLabel Label(Color colour) => new TextLabel
        {
            TextColor = colour,
            HorizontalAlignment = HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center,
            Ellipsis = true,
        };

        // A slim bar on the picture: the camera's name, then the message on up to
        // two lines. Neither given: no bar.
        private void SetText(string title, string message)
        {
            bool hasTitle = !string.IsNullOrEmpty(title);
            bool hasMessage = !string.IsNullOrEmpty(message);
            float basis = _size.Width >= 800 ? 20 : _size.Width >= 600 ? 17 : 15;
            int pixels = (int)(basis * _textScale);
            int lines = hasMessage && message.Length * pixels / 2 > _size.Width - 32 ? 2 : 1;
            int titleHeight = hasTitle ? pixels * 4 / 3 : 0;
            int messageHeight = hasMessage ? pixels * 3 / 2 * lines : 0;
            int height = titleHeight + messageHeight + (hasTitle || hasMessage ? 8 : 0);

            _title.Text = title ?? string.Empty;
            _title.PixelSize = pixels * 0.85f;
            _title.Size2D = new Size2D(_size.Width - 32, titleHeight);
            _title.Position2D = new Position2D(16, 4);
            Visible(_title, hasTitle);
            _message.Text = message ?? string.Empty;
            _message.PixelSize = pixels;
            _message.MultiLine = lines > 1;
            _message.Size2D = new Size2D(_size.Width - 32, messageHeight);
            _message.Position2D = new Position2D(16, 4 + titleHeight);
            Visible(_message, hasMessage);
            _caption.Size2D = new Size2D(_size.Width, height);
            _caption.Position2D = new Position2D(
                Margin, _textOnTop ? Margin : Margin + _size.Height - height);
            Visible(_caption, height > 0);
        }

        // Show the newest picture; keep the previous two underneath while it loads.
        private void Draw()
        {
            string newest = null;
            while (_frames.TryDequeue(out var path))
            {
                Delete(newest);
                newest = path;
            }
            if (newest == null || _video == null)
            {
                return;
            }
            var picture = new ImageView { Size2D = _size, ResourceUrl = newest };
            _video.Add(picture);
            _pictures.Add(picture);
            while (_pictures.Count > 3)
            {
                var old = _pictures[0];
                _pictures.RemoveAt(0);
                var file = old.ResourceUrl;
                _video.Remove(old);
                old.Dispose();
                Delete(file);
            }
        }

        // Read the MJPEG stream until closed, reconnecting if it drops.
        private void Fetch(string url, int run, CancellationToken token)
        {
            string dir = Application.Current.DirectoryInfo.Data;
            int count = 0;
            while (!token.IsCancellationRequested)
            {
                try
                {
                    using (var response = Http.GetAsync(url, HttpCompletionOption.ResponseHeadersRead, token)
                        .GetAwaiter().GetResult())
                    // Closing the response unblocks a read when the box closes.
                    using (token.Register(response.Dispose))
                    {
                        response.EnsureSuccessStatusCode();
                        using (var body = new BufferedStream(
                            response.Content.ReadAsStreamAsync().GetAwaiter().GetResult(), 65536))
                        {
                            byte[] jpeg;
                            while (!token.IsCancellationRequested && (jpeg = NextFrame(body)) != null)
                            {
                                string path = System.IO.Path.Combine(
                                    dir, "corner-" + run + "-" + (++count) + ".jpg");
                                File.WriteAllBytes(path, jpeg);
                                _frames.Enqueue(path);
                            }
                        }
                    }
                }
                catch (Exception ex)
                {
                    if (!token.IsCancellationRequested)
                    {
                        Log.Error(Tag, "STREAM_FAIL " + ex.GetType().Name + ": " + ex.Message);
                    }
                }
                token.WaitHandle.WaitOne(1000);
            }
        }

        // One multipart part: headers with Content-length, a blank line, the JPEG.
        private static byte[] NextFrame(Stream body)
        {
            int length = -1;
            while (true)
            {
                string line = ReadLine(body);
                if (line == null)
                {
                    return null;
                }
                if (line.StartsWith("Content-length:", StringComparison.OrdinalIgnoreCase))
                {
                    int.TryParse(line.Substring(15).Trim(), out length);
                }
                else if (line.Length == 0 && length >= 0)
                {
                    break;
                }
            }
            if (length == 0 || length > MaxFrameBytes)
            {
                return null;
            }
            var jpeg = new byte[length];
            int read = 0;
            while (read < length)
            {
                int got = body.Read(jpeg, read, length - read);
                if (got <= 0)
                {
                    return null;
                }
                read += got;
            }
            return jpeg;
        }

        private static string ReadLine(Stream body)
        {
            var line = new StringBuilder();
            int c;
            while ((c = body.ReadByte()) >= 0)
            {
                if (c == '\n')
                {
                    return line.ToString().TrimEnd('\r');
                }
                if (line.Length > 200)
                {
                    return null; // not the stream we expect
                }
                line.Append((char)c);
            }
            return null;
        }

        private static void Visible(View view, bool visible)
        {
            if (visible)
            {
                view.Show();
            }
            else
            {
                view.Hide();
            }
        }

        private static void Delete(string path)
        {
            if (path != null)
            {
                Try("delete", () => File.Delete(path));
            }
        }

        private static void Try(string what, Action action)
        {
            try
            {
                action();
            }
            catch (Exception ex)
            {
                Log.Error(Tag, "CORNER_" + what + " " + ex.GetType().Name + ": " + ex.Message);
            }
        }
    }
}
