window.BEATMAP = {
 "_about": "The one score for picture and sound. 120 BPM, 30 bars, 60 s. Every time is in seconds and sits on the grid (beat = 0.5 s, bar = 2 s). scripts/make_audio.py places sounds from it; scripts/build_assets.py copies it into composition/assets/beatmap.js for the timeline.",
 "bpm": 120,
 "beat": 0.5,
 "bar": 2.0,
 "duration": 60.0,
 "chords": [
  "Am",
  "F",
  "C",
  "G"
 ],
 "sections": [
  {
   "id": "tension",
   "start": 0.0,
   "end": 4.0
  },
  {
   "id": "silence",
   "start": 4.0,
   "end": 5.0
  },
  {
   "id": "intro",
   "start": 5.0,
   "end": 8.0
  },
  {
   "id": "build",
   "start": 8.0,
   "end": 14.0
  },
  {
   "id": "groove",
   "start": 14.0,
   "end": 28.0
  },
  {
   "id": "night",
   "start": 28.0,
   "end": 34.0
  },
  {
   "id": "drop",
   "start": 34.0,
   "end": 52.0
  },
  {
   "id": "rise",
   "start": 52.0,
   "end": 56.0
  },
  {
   "id": "resolve",
   "start": 56.0,
   "end": 60.0
  }
 ],
 "shots": [
  {
   "id": "s01-flood",
   "start": 0.0,
   "end": 4.0
  },
  {
   "id": "s02-silence",
   "start": 4.0,
   "end": 8.0
  },
  {
   "id": "s03-normal",
   "start": 8.0,
   "end": 14.0
  },
  {
   "id": "s04-grid",
   "start": 14.0,
   "end": 20.0
  },
  {
   "id": "s05-story",
   "start": 20.0,
   "end": 26.0
  },
  {
   "id": "s06-night",
   "start": 26.0,
   "end": 40.0
  },
  {
   "id": "s07-proof",
   "start": 40.0,
   "end": 46.0
  },
  {
   "id": "s08-log",
   "start": 46.0,
   "end": 52.0
  },
  {
   "id": "s09-grow",
   "start": 52.0,
   "end": 56.0
  },
  {
   "id": "s10-end",
   "start": 56.0,
   "end": 60.0
  }
 ],
 "cues": {
  "flood_notices": [
   0.0,
   0.25,
   0.5,
   0.75,
   1.0,
   1.25,
   1.5,
   1.75,
   2.0,
   2.25,
   2.5,
   2.75,
   3.0,
   3.125,
   3.25,
   3.375,
   3.5,
   3.625,
   3.75
  ],
  "flood_words": [
   0.0,
   2.0,
   2.5,
   3.0
  ],
  "reverse_riser_end": 4.0,
  "watch_in": 5.0,
  "question": 5.0,
  "title": 6.0,
  "city_bars": [
   8.0,
   8.5,
   9.0,
   9.5,
   10.0
  ],
  "normal_line2": 10.5,
  "marker_sweep": [
   11.0,
   12.5
  ],
  "marker_rows": [
   11.0,
   11.375,
   11.75,
   12.125,
   12.5
  ],
  "helsinki_alarm": 11.0,
  "delhi_calm": 12.5,
  "grid_draw": 14.0,
  "grid_quiet_cells": [
   15.0,
   15.5,
   16.0
  ],
  "grid_line2": 16.5,
  "tell_them": 18.0,
  "story_ticks": [
   20.0,
   20.25,
   20.5,
   20.75,
   21.0,
   21.25,
   21.5,
   21.75,
   22.0,
   22.25,
   22.5,
   22.75
  ],
  "story_grey": 23.0,
  "story_messages": [
   23.5,
   24.0,
   24.5
  ],
  "story_bracket": 25.0,
  "chip_tap": 26.0,
  "clock": [
   [
    26.5,
    "22:00"
   ],
   [
    30.0,
    "04:50"
   ],
   [
    32.0,
    "05:50"
   ],
   [
    34.0,
    "06:30"
   ]
  ],
  "held": 30.0,
  "same_story": [
   32.0
  ],
  "drop": 34.0,
  "why_tap": 37.0,
  "proof_cards": [
   40.0,
   42.0,
   44.0
  ],
  "glitch_stamp": 41.0,
  "log_rows_start": 46.0,
  "log_rows_step": 0.125,
  "log_line2": 48.0,
  "log_push": 49.75,
  "log_trace_lines": [
   50.0,
   50.5,
   51.0
  ],
  "layer_tiles": [
   52.0,
   53.5
  ],
  "stubs_amber": 53.5,
  "future_icons": [
   54.0,
   54.5,
   55.0
  ],
  "end_lines": [
   56.0,
   57.0
  ],
  "end_repo": 58.0,
  "final_chord": 58.0,
  "night_ticks": [
   27.0,
   27.5,
   28.0,
   28.5,
   29.0,
   29.5
  ],
  "why_layers": [
   37.5,
   38.0,
   38.5,
   39.0
  ]
 },
 "_night_note": "Shot 6 follows the real replayed night: silent hours tick by (27.0-29.5), the spike at 04:50 is held for quiet hours (30.0), 05:50 is the same story (32.0), the check-in sends at 06:30 (34.0, the drop)."
};
