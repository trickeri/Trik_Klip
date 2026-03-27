import { useState, useRef, useCallback } from "react";

const DEMO_TRANSCRIPT = `[00:00:00] Hey what's up everyone, welcome back. So today I want to talk about something that completely changed how I think about money, and I wish someone had told me this when I was 22.

[00:01:15] So I grew up broke. Like genuinely broke. My mom was a single parent working two jobs, we had to choose between groceries and electricity sometimes. And I swore to myself that I would never be in that situation.

[00:02:30] Fast forward to when I'm 26, I'm making six figures at this tech company, and you know what? I was still broke. I had a nice apartment, new car, going out every weekend. Completely lifestyle-inflated my way into having nothing.

[00:04:00] And then I met this older guy at a conference, must have been in his 60s, and he just looked at my watch and said "nice watch, how many hours did you trade for that?" I didn't even know what to say. He walked away before I could answer.

[00:05:30] That question haunted me for weeks. So I did the math. My hourly rate after tax was about $45 an hour. That watch cost $800. So I had traded almost 18 hours of my life for something that told me the time when my phone was right there in my pocket.

[00:07:00] I started doing this for everything. Dinner out? Three hours. New sneakers? Eight hours. That weekend trip? Forty hours. And suddenly I realized I had no idea what my time was actually worth to me.

[00:08:30] Here's the thing nobody tells you — money is just stored time. When you spend money, you're spending time you already lived. And when you save and invest it, you're buying future time, time you don't have to trade away.

[00:10:00] So I started asking one question before every purchase: "is this worth the hours?" Not the dollars. The hours. And it completely rewired my brain around spending.

[00:11:30] Within 18 months I had paid off my car, had a six-month emergency fund, and started maxing my 401k. Not because I earned more — my salary barely changed. Just because I changed the lens.

[00:13:00] Alright let's switch gears, chat wants to talk about the new GPU releases from Nvidia. So let's pull that up...

[00:14:00] Yeah the 5090 is wild, the VRAM alone is just — look if you're a developer working on local models this changes everything. The memory bandwidth is insane compared to previous gen.

[00:16:00] But here's what I actually think is underrated about this release — it's not the flagship that matters, it's the mid-range. The 5070 at that price point is going to democratize local AI inference in a way we haven't seen.

[00:18:00] Like imagine running a capable local LLM on a $500 card. That's the unlock. That changes the privacy equation completely because suddenly you don't need to send your data to anyone's cloud.

[00:19:30] Someone in chat asks if I'm worried about AI taking jobs. Honestly? The jobs I'm worried about aren't the ones people talk about. Everyone says coding, writing, whatever. Those are fine, those people will adapt.

[00:20:30] The jobs I think are genuinely at risk are the ones in the middle — like the junior analyst, the entry-level copywriter, the QA tester. The rungs on the ladder that people use to get experience. If those disappear, how does the next generation build skills?

[00:22:00] That's the thing that keeps me up at night. Not that AI replaces experts. It's that it might skip the training ground entirely and we won't notice until there's no pipeline of people who know how to do anything deeply.

[00:24:00] Anyway that's probably a whole separate video. Let me show you this setup I've been working on...`;

function parseTranscript(text) {
  const lines = text.trim().split("\n").filter(l => l.trim());
  const segments = [];
  for (const line of lines) {
    const match = line.match(/^\[(\d{2}:\d{2}:\d{2})\]\s*(.*)/);
    if (match) {
      const [, ts, content] = match;
      const parts = ts.split(":").map(Number);
      const seconds = parts[0] * 3600 + parts[1] * 60 + parts[2];
      segments.push({ start: seconds, text: content.trim() });
    }
  }
  for (let i = 0; i < segments.length - 1; i++) {
    segments[i].end = segments[i + 1].start;
  }
  if (segments.length) segments[segments.length - 1].end = segments[segments.length - 1].start + 60;
  return segments;
}

function fmtTime(sec) {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function buildWindows(segments, windowSec = 300, overlapSec = 60) {
  if (!segments.length) return [];
  const total = segments[segments.length - 1].end;
  const step = windowSec - overlapSec;
  const windows = [];
  for (let t = 0; t < total; t += step) {
    const end = Math.min(t + windowSec, total);
    const chunk = segments.filter(s => s.start >= t && s.start < end);
    if (chunk.length) windows.push({ start: t, end, text: chunk.map(s => s.text).join(" ") });
  }
  return windows;
}

const TYPE_COLORS = {
  story: "#f59e0b",
  advice: "#10b981",
  moment: "#8b5cf6",
  debate: "#ef4444",
  rant: "#f97316",
  revelation: "#06b6d4",
  other: "#6b7280",
};

const TYPE_ICONS = {
  story: "📖",
  advice: "💡",
  moment: "⚡",
  debate: "🔥",
  rant: "📢",
  revelation: "✨",
  other: "🎬",
};

// ── Score bar ─────────────────────────────────────────────────────────────────
function ScoreBar({ score }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <div style={{
        display: "flex", gap: 2,
        background: "rgba(255,255,255,0.05)",
        borderRadius: 4, padding: "3px 5px"
      }}>
        {Array.from({ length: 10 }).map((_, i) => (
          <div key={i} style={{
            width: 8, height: 14, borderRadius: 2,
            background: i < score
              ? score >= 8 ? "#10b981" : score >= 5 ? "#f59e0b" : "#ef4444"
              : "rgba(255,255,255,0.08)"
          }} />
        ))}
      </div>
      <span style={{ fontSize: 12, color: "#9ca3af", fontFamily: "monospace" }}>{score}/10</span>
    </div>
  );
}

// ── Clip card ─────────────────────────────────────────────────────────────────
function ClipCard({ clip, index }) {
  const [expanded, setExpanded] = useState(false);
  const typeColor = TYPE_COLORS[clip.content_type] || "#6b7280";
  const typeIcon = TYPE_ICONS[clip.content_type] || "🎬";
  const duration = Math.round(clip.clip_end - clip.clip_start);

  return (
    <div style={{
      background: "rgba(255,255,255,0.03)",
      border: `1px solid rgba(255,255,255,0.08)`,
      borderLeft: `3px solid ${typeColor}`,
      borderRadius: 12,
      padding: "20px 24px",
      cursor: "pointer",
      transition: "all 0.2s",
      position: "relative",
      overflow: "hidden"
    }}
      onClick={() => setExpanded(e => !e)}
      onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.05)"}
      onMouseLeave={e => e.currentTarget.style.background = "rgba(255,255,255,0.03)"}
    >
      {/* rank badge */}
      <div style={{
        position: "absolute", top: 16, right: 16,
        width: 28, height: 28, borderRadius: "50%",
        background: "rgba(255,255,255,0.07)",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 11, fontWeight: 700, color: "#9ca3af", fontFamily: "monospace"
      }}>#{index + 1}</div>

      {/* header row */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: 10, marginBottom: 10, paddingRight: 36 }}>
        <span style={{ fontSize: 20 }}>{typeIcon}</span>
        <div>
          <div style={{ fontWeight: 700, fontSize: 15, color: "#f3f4f6", lineHeight: 1.3 }}>{clip.title}</div>
          <div style={{ fontSize: 11, color: typeColor, textTransform: "uppercase", letterSpacing: 1, marginTop: 2 }}>
            {clip.content_type}
          </div>
        </div>
      </div>

      {/* score + duration row */}
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 12 }}>
        <ScoreBar score={clip.virality_score} />
        <span style={{
          fontSize: 12, color: "#9ca3af", background: "rgba(255,255,255,0.07)",
          padding: "2px 8px", borderRadius: 4, fontFamily: "monospace"
        }}>
          {Math.floor(duration / 60)}m {duration % 60}s
        </span>
      </div>

      {/* timestamp pills */}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
        <div style={{
          fontSize: 11, padding: "4px 10px", borderRadius: 6,
          background: "rgba(255,255,255,0.06)", color: "#d1d5db",
          fontFamily: "monospace"
        }}>
          📦 Window {fmtTime(clip.segment_start)} → {fmtTime(clip.segment_end)}
        </div>
        <div style={{
          fontSize: 11, padding: "4px 10px", borderRadius: 6,
          background: `${typeColor}22`, color: typeColor,
          fontFamily: "monospace", fontWeight: 700
        }}>
          ✂️ Clip {fmtTime(clip.clip_start)} → {fmtTime(clip.clip_end)}
        </div>
      </div>

      {/* hook */}
      <p style={{ fontSize: 13, color: "#9ca3af", margin: 0, lineHeight: 1.5 }}>{clip.hook}</p>

      {/* expanded details */}
      {expanded && clip.transcript_excerpt && (
        <div style={{
          marginTop: 14, paddingTop: 14,
          borderTop: "1px solid rgba(255,255,255,0.07)"
        }}>
          <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 6, textTransform: "uppercase", letterSpacing: 1 }}>
            Excerpt
          </div>
          <p style={{
            fontSize: 13, color: "#c3c6cb", fontStyle: "italic",
            margin: 0, lineHeight: 1.6,
            borderLeft: `2px solid ${typeColor}`,
            paddingLeft: 12
          }}>
            "{clip.transcript_excerpt}"
          </p>

          {/* ffmpeg command */}
          <div style={{ marginTop: 14 }}>
            <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 6, textTransform: "uppercase", letterSpacing: 1 }}>
              FFmpeg Command
            </div>
            <div style={{
              fontFamily: "monospace", fontSize: 11,
              background: "rgba(0,0,0,0.4)", borderRadius: 8,
              padding: "10px 12px", color: "#86efac",
              wordBreak: "break-all", lineHeight: 1.6
            }}>
              ffmpeg -ss {clip.clip_start.toFixed(2)} -i input.mp4 -t {(clip.clip_end - clip.clip_start).toFixed(2)} -c:v copy -c:a aac "{clip.title.replace(/[^a-z0-9]/gi, "_").toLowerCase()}.mp4"
            </div>
          </div>
        </div>
      )}

      <div style={{ fontSize: 11, color: "#4b5563", marginTop: 10, textAlign: "right" }}>
        {expanded ? "▲ collapse" : "▼ expand"}
      </div>
    </div>
  );
}

// ── Main app ──────────────────────────────────────────────────────────────────
export default function StreamClipper() {
  const [transcript, setTranscript] = useState(DEMO_TRANSCRIPT);
  const [clips, setClips] = useState([]);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [error, setError] = useState(null);
  const [analysisLog, setAnalysisLog] = useState([]);
  const abortRef = useRef(null);

  const analyze = useCallback(async () => {
    setLoading(true);
    setClips([]);
    setError(null);
    setAnalysisLog([]);

    try {
      const segments = parseTranscript(transcript);
      if (!segments.length) throw new Error("No timestamped segments found. Use format: [HH:MM:SS] text");

      const windows = buildWindows(segments, 300, 60);
      setProgress({ done: 0, total: windows.length });

      const candidates = [];

      for (let i = 0; i < windows.length; i++) {
        const win = windows[i];

        setAnalysisLog(l => [...l, `Analyzing window ${fmtTime(win.start)} → ${fmtTime(win.end)}...`]);

        const systemPrompt = `You are an expert short-form content strategist. Analyze transcript chunks from long-form streams to find viral 1–3 minute clips.

A great clip has: clear narrative arc, surprising reveal, strong opinion, emotional/funny moment, actionable advice, or memorable monologue.

Return ONLY valid JSON with this schema:
{"has_clip":true/false,"virality_score":1-10,"content_type":"story|advice|moment|debate|rant|revelation|other","title":"max 60 chars","hook":"one sentence why someone would watch","clip_start_offset":seconds_from_window_start,"clip_end_offset":seconds_from_window_start,"transcript_excerpt":"1-2 most compelling sentences"}

If no compelling clip, return {"has_clip":false}.
clip_end_offset - clip_start_offset must be 60-180 seconds.`;

        const userMsg = `Window: ${fmtTime(win.start)} → ${fmtTime(win.end)}\n\nTranscript:\n${win.text}`;

        const resp = await fetch("https://api.anthropic.com/v1/messages", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            model: "claude-sonnet-4-20250514",
            max_tokens: 600,
            system: systemPrompt,
            messages: [{ role: "user", content: userMsg }]
          })
        });

        const data = await resp.json();
        if (data.error) throw new Error(data.error.message);

        const raw = data.content[0].text.replace(/```json|```/g, "").trim();
        try {
          const result = JSON.parse(raw);
          if (result.has_clip) {
            const cs = win.start + (result.clip_start_offset || 0);
            const ce = win.start + (result.clip_end_offset || 60);
            candidates.push({
              ...result,
              segment_start: win.start,
              segment_end: win.end,
              clip_start: Math.max(cs, win.start),
              clip_end: Math.min(ce, win.end),
            });
          }
        } catch {}

        setProgress({ done: i + 1, total: windows.length });
      }

      // Sort by virality, deduplicate overlapping clips
      candidates.sort((a, b) => b.virality_score - a.virality_score);
      const selected = [];
      const usedRanges = [];

      for (const c of candidates) {
        const overlap = usedRanges.some(([s, e]) => !(c.clip_end <= s || c.clip_start >= e));
        if (!overlap) {
          usedRanges.push([c.clip_start, c.clip_end]);
          selected.push(c);
        }
        if (selected.length >= 10) break;
      }

      setClips(selected);
      setAnalysisLog(l => [...l, `✓ Analysis complete — found ${selected.length} clip suggestions`]);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [transcript]);

  const progressPct = progress.total ? Math.round((progress.done / progress.total) * 100) : 0;

  return (
    <div style={{
      minHeight: "100vh",
      background: "#0a0a0f",
      color: "#f3f4f6",
      fontFamily: "'DM Sans', 'Segoe UI', sans-serif",
      padding: "0 0 60px"
    }}>
      {/* header */}
      <div style={{
        padding: "36px 40px 24px",
        borderBottom: "1px solid rgba(255,255,255,0.06)"
      }}>
        <div style={{ maxWidth: 900, margin: "0 auto" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 8 }}>
            <div style={{
              width: 40, height: 40, borderRadius: 10,
              background: "linear-gradient(135deg, #7c3aed, #2563eb)",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 20
            }}>✂️</div>
            <div>
              <h1 style={{ margin: 0, fontSize: 24, fontWeight: 800, letterSpacing: -0.5 }}>
                StreamClipper
              </h1>
              <p style={{ margin: 0, fontSize: 13, color: "#6b7280" }}>
                Paste a timestamped transcript → get short-form clip suggestions
              </p>
            </div>
          </div>
        </div>
      </div>

      <div style={{ maxWidth: 900, margin: "0 auto", padding: "32px 40px 0" }}>

        {/* transcript input */}
        <div style={{ marginBottom: 20 }}>
          <div style={{
            display: "flex", justifyContent: "space-between",
            alignItems: "center", marginBottom: 8
          }}>
            <label style={{ fontSize: 13, fontWeight: 600, color: "#d1d5db" }}>
              Timestamped Transcript
            </label>
            <span style={{ fontSize: 12, color: "#4b5563" }}>
              Format: [HH:MM:SS] text content here
            </span>
          </div>
          <textarea
            value={transcript}
            onChange={e => setTranscript(e.target.value)}
            rows={12}
            style={{
              width: "100%",
              background: "rgba(255,255,255,0.03)",
              border: "1px solid rgba(255,255,255,0.1)",
              borderRadius: 10,
              padding: "14px 16px",
              color: "#e5e7eb",
              fontFamily: "monospace",
              fontSize: 12,
              lineHeight: 1.7,
              resize: "vertical",
              outline: "none",
              boxSizing: "border-box"
            }}
            placeholder="[00:00:00] Hey everyone, welcome back..."
          />
          <p style={{ fontSize: 12, color: "#4b5563", margin: "6px 0 0" }}>
            💡 Use Whisper, AssemblyAI, or any speech-to-text tool to generate timestamped transcripts from your MP4 file. The Python CLI in the repo handles this automatically.
          </p>
        </div>

        {/* analyze button */}
        <button
          onClick={analyze}
          disabled={loading || !transcript.trim()}
          style={{
            width: "100%",
            padding: "14px",
            background: loading
              ? "rgba(124,58,237,0.3)"
              : "linear-gradient(135deg, #7c3aed, #2563eb)",
            border: "none",
            borderRadius: 10,
            color: "#fff",
            fontSize: 15,
            fontWeight: 700,
            cursor: loading ? "not-allowed" : "pointer",
            transition: "opacity 0.2s",
            letterSpacing: 0.3
          }}
        >
          {loading ? `Analyzing... ${progressPct}%` : "✂️ Find Clips"}
        </button>

        {/* progress bar */}
        {loading && (
          <div style={{ marginTop: 12 }}>
            <div style={{
              height: 4, background: "rgba(255,255,255,0.08)",
              borderRadius: 99, overflow: "hidden"
            }}>
              <div style={{
                height: "100%", width: `${progressPct}%`,
                background: "linear-gradient(90deg, #7c3aed, #2563eb)",
                transition: "width 0.3s", borderRadius: 99
              }} />
            </div>
            <div style={{
              fontSize: 12, color: "#6b7280", marginTop: 8,
              maxHeight: 80, overflowY: "auto", fontFamily: "monospace"
            }}>
              {analysisLog.slice(-3).map((l, i) => (
                <div key={i}>{l}</div>
              ))}
            </div>
          </div>
        )}

        {/* error */}
        {error && (
          <div style={{
            marginTop: 16, padding: "12px 16px",
            background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)",
            borderRadius: 8, color: "#fca5a5", fontSize: 13
          }}>
            ⚠️ {error}
          </div>
        )}

        {/* results */}
        {clips.length > 0 && (
          <div style={{ marginTop: 32 }}>
            <div style={{
              display: "flex", justifyContent: "space-between",
              alignItems: "center", marginBottom: 16
            }}>
              <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>
                {clips.length} Clip Suggestions
              </h2>
              <div style={{ display: "flex", gap: 8 }}>
                {["story","advice","moment","debate","rant","revelation"].map(type => (
                  clips.some(c => c.content_type === type) && (
                    <span key={type} style={{
                      fontSize: 11, padding: "3px 8px", borderRadius: 4,
                      background: `${TYPE_COLORS[type]}22`,
                      color: TYPE_COLORS[type],
                      textTransform: "uppercase", letterSpacing: 0.5
                    }}>
                      {TYPE_ICONS[type]} {type}
                    </span>
                  )
                ))}
              </div>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {clips.map((clip, i) => (
                <ClipCard key={i} clip={clip} index={i} />
              ))}
            </div>

            {/* summary table */}
            <div style={{
              marginTop: 28, padding: "20px 24px",
              background: "rgba(255,255,255,0.02)",
              border: "1px solid rgba(255,255,255,0.07)",
              borderRadius: 12
            }}>
              <h3 style={{ margin: "0 0 14px", fontSize: 14, fontWeight: 600, color: "#9ca3af" }}>
                Quick Reference Table
              </h3>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12, fontFamily: "monospace" }}>
                <thead>
                  <tr style={{ color: "#6b7280" }}>
                    {["#","Title","Clip In","Clip Out","Duration","Score"].map(h => (
                      <th key={h} style={{ textAlign: "left", padding: "4px 8px", fontWeight: 600 }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {clips.map((c, i) => (
                    <tr key={i} style={{ borderTop: "1px solid rgba(255,255,255,0.05)", color: "#d1d5db" }}>
                      <td style={{ padding: "6px 8px", color: "#6b7280" }}>{i + 1}</td>
                      <td style={{ padding: "6px 8px", maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.title}</td>
                      <td style={{ padding: "6px 8px", color: "#86efac" }}>{fmtTime(c.clip_start)}</td>
                      <td style={{ padding: "6px 8px", color: "#86efac" }}>{fmtTime(c.clip_end)}</td>
                      <td style={{ padding: "6px 8px" }}>{Math.round(c.clip_end - c.clip_start)}s</td>
                      <td style={{ padding: "6px 8px", color: c.virality_score >= 8 ? "#10b981" : c.virality_score >= 5 ? "#f59e0b" : "#ef4444" }}>
                        {c.virality_score}/10
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
