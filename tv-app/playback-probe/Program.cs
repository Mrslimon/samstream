using System;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Text;
using System.Threading;
using Tizen.Applications;

// Headless service on the TV. Watches the video decoder's hardware interrupt (sdp_dv) and tells
// Home Assistant whether video is playing, paused or absent. Netflix etc. never report this themselves.
//   measured on QE55Q64D / Tizen 9: playing ~50/s, paused ~24/s, no video 0/s
class PlaybackProbe : ServiceApplication
{
    // Set to your Home Assistant webhook before building (see README.md).
    const string Webhook = "http://homeassistant.local:8123/api/webhook/CHANGE_ME";
    const int PeriodMs = 250;
    const int WindowSamples = 4;          // average over 1 s; single 250 ms samples jitter 44..68
    const int PlayingAbove = 38;          // calibration knobs: thresholds in interrupts per second
    const int PausedAbove = 14;
    const int HeartbeatSamples = 30_000 / PeriodMs;

    static readonly HttpClient Http = new HttpClient { Timeout = TimeSpan.FromSeconds(3) };
    readonly long[] _window = new long[WindowSamples];
    int _filled, _sinceSend;
    long _lastCount = -1;
    string _state = "";
    Timer _timer;

    protected override void OnCreate()
    {
        base.OnCreate();
        _timer = new Timer(_ => Poll(), null, 0, PeriodMs);
    }

    void Poll()
    {
        long count = DecoderCount();
        if (count < 0) return;
        if (_lastCount >= 0)
        {
            _window[_filled++ % WindowSamples] = (count - _lastCount) * 1000 / PeriodMs;
        }
        _lastCount = count;
        if (_filled < WindowSamples) return;

        long rate = _window.Sum() / WindowSamples;
        string state = rate >= PlayingAbove ? "playing" : rate >= PausedAbove ? "paused" : "none";

        if (state != _state || ++_sinceSend >= HeartbeatSamples)
        {
            _state = state;
            _sinceSend = 0;
            Send(state, rate);
        }
    }

    // Total sdp_dv interrupt count across CPUs, or -1 if the line isn't there.
    static long DecoderCount()
    {
        try
        {
            var lines = File.ReadAllLines("/proc/interrupts");
            int cpus = lines[0].Split((char[])null, StringSplitOptions.RemoveEmptyEntries).Count(t => t.StartsWith("CPU"));
            var line = lines.FirstOrDefault(l => l.Contains("sdp_dv"));
            if (line == null) return -1;
            return line.Split((char[])null, StringSplitOptions.RemoveEmptyEntries)
                .Skip(1).Take(cpus).Sum(long.Parse);
        }
        catch { return -1; }
    }

    static void Send(string state, long rate)
    {
        try
        {
            var json = $"{{\"state\":\"{state}\",\"rate\":{rate}}}";
            Http.PostAsync(Webhook, new StringContent(json, Encoding.UTF8, "application/json")).Wait();
        }
        catch { } // HA unreachable: the next change or heartbeat retries
    }

    static void Main(string[] args) => new PlaybackProbe().Run(args);
}
