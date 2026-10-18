window.DATA = {
 "source_repo_commit": "aec7e20",
 "cities": [
  {
   "city": "Helsinki",
   "median": 4.2
  },
  {
   "city": "Los Angeles",
   "median": 10.0
  },
  {
   "city": "Bengaluru",
   "median": 20.7
  },
  {
   "city": "Dubai",
   "median": 41.0
  },
  {
   "city": "Delhi",
   "median": 45.9
  }
 ],
 "mumbai": [
  {
   "t": "11:00",
   "v": 65
  },
  {
   "t": "12:00",
   "v": 75
  },
  {
   "t": "13:00",
   "v": 980
  },
  {
   "t": "14:00",
   "v": 90
  },
  {
   "t": "15:00",
   "v": 89
  }
 ],
 "mumbai_day": "14 October",
 "replay": {
  "run": "demo",
  "weeks": 12.9,
  "decisions": 15345,
  "notices": 251,
  "weekly": [
   {
    "user": "aino",
    "city": "Helsinki",
    "sensitivity": "high",
    "per_week": 1.6,
    "events_per_week": 1.6
   },
   {
    "user": "maya",
    "city": "Los Angeles",
    "sensitivity": "default",
    "per_week": 1.8,
    "events_per_week": 1.8
   },
   {
    "user": "priya",
    "city": "Bengaluru",
    "sensitivity": "default",
    "per_week": 3.1,
    "events_per_week": 1.6
   },
   {
    "user": "omar",
    "city": "Dubai",
    "sensitivity": "low",
    "per_week": 1.6,
    "events_per_week": 1.6
   },
   {
    "user": "arjun",
    "city": "Delhi",
    "sensitivity": "default",
    "per_week": 4.6,
    "events_per_week": 2.3
   },
   {
    "user": "meera",
    "city": "Delhi",
    "sensitivity": "high",
    "per_week": 4.7,
    "events_per_week": 4.7
   }
  ]
 },
 "watch": {
  "user": {
   "id": "arjun",
   "name": "Arjun",
   "city": "Delhi"
  },
  "check_in": {
   "id": "ntf_45",
   "body": "Delhi's air has been unhealthy since 4:50am, worse than a usual morning here, the second bad morning this week. Best to skip the outdoor run for now.",
   "action": "skip the outdoor run",
   "band": "unhealthy",
   "t": "06:30"
  },
  "cleared": {
   "body": "Delhi's air is back to its usual level after 14 hours. Good time to go for an easy run.",
   "action": "go for an easy run"
  },
  "why": [
   "Jumped sharply at 4:50am",
   "Held overnight (quiet hours), sent at your 06:30 check-in",
   "Your first message today"
  ],
  "trace": [
   {
    "layer": "D2",
    "passed": true,
    "code": null,
    "values": {
     "state": "ACTIVE",
     "started_at": "2026-08-08T23:20:00+00:00",
     "hours": 1.7,
     "ended_at": null,
     "peak": {
      "pm25": 82,
      "at": "2026-08-08T22:30:00+00:00",
      "band": "unhealthy"
     }
    }
   },
   {
    "layer": "D8",
    "passed": true,
    "code": null,
    "values": {
     "check_in": "06:30",
     "absorbed_held": 1,
     "hours_considered": 6,
     "band": "unhealthy",
     "typical_band": "usg",
     "ewma": 2.2007825388442077,
     "recent_notice": false
    }
   },
   {
    "layer": "D5",
    "passed": true,
    "code": null,
    "values": {
     "candidates": 1,
     "kept": "check_in"
    }
   },
   {
    "layer": "D6",
    "passed": true,
    "code": null,
    "values": {
     "response": "notify"
    }
   },
   {
    "layer": "D7",
    "passed": true,
    "code": null,
    "values": {
     "sent_today": 0,
     "max_per_day": 3
    }
   },
   {
    "layer": "D8",
    "passed": true,
    "code": null,
    "values": {
     "local_time": "06:30",
     "quiet_hours": true,
     "check_in_wins": true
    }
   },
   {
    "layer": "A",
    "passed": true,
    "code": "SENT_CHECK_IN",
    "values": {
     "compose": "check_in"
    }
   }
  ],
  "night": [
   {
    "t": "19:50",
    "outcome": "no_event",
    "code": "NO_TRIGGER",
    "reason": "Nothing unusual."
   },
   {
    "t": "20:50",
    "outcome": "no_event",
    "code": "NO_TRIGGER",
    "reason": "Nothing unusual."
   },
   {
    "t": "21:50",
    "outcome": "no_event",
    "code": "NO_TRIGGER",
    "reason": "Nothing unusual."
   },
   {
    "t": "22:50",
    "outcome": "no_event",
    "code": "NO_TRIGGER",
    "reason": "Nothing unusual."
   },
   {
    "t": "23:50",
    "outcome": "no_event",
    "code": "NO_TRIGGER",
    "reason": "Nothing unusual."
   },
   {
    "t": "00:50",
    "outcome": "no_event",
    "code": "NO_TRIGGER",
    "reason": "Nothing unusual."
   },
   {
    "t": "01:50",
    "outcome": "no_event",
    "code": "NO_TRIGGER",
    "reason": "Nothing unusual."
   },
   {
    "t": "02:50",
    "outcome": "no_event",
    "code": "NO_TRIGGER",
    "reason": "Nothing unusual."
   },
   {
    "t": "03:50",
    "outcome": "no_event",
    "code": "NO_TRIGGER",
    "reason": "Nothing unusual."
   },
   {
    "t": "04:50",
    "outcome": "held",
    "code": "QUIET_HOURS_HELD",
    "reason": "Held: quiet hours until 07:00."
   },
   {
    "t": "05:50",
    "outcome": "no_event",
    "code": "EPISODE_CONTINUES",
    "reason": "The same bad period is continuing; nothing new to say."
   },
   {
    "t": "06:30",
    "outcome": "sent",
    "code": "SENT_CHECK_IN",
    "reason": "Sent at your check-in time."
   },
   {
    "t": "06:50",
    "outcome": "suppressed",
    "code": "DEDUP_SAME_BAND",
    "reason": "Already told you about this level; nothing new to say."
   },
   {
    "t": "07:50",
    "outcome": "suppressed",
    "code": "DEDUP_SAME_BAND",
    "reason": "Already told you about this level; nothing new to say."
   },
   {
    "t": "08:50",
    "outcome": "suppressed",
    "code": "DEDUP_SAME_BAND",
    "reason": "Already told you about this level; nothing new to say."
   },
   {
    "t": "09:50",
    "outcome": "suppressed",
    "code": "DEDUP_SAME_BAND",
    "reason": "Already told you about this level; nothing new to say."
   },
   {
    "t": "10:50",
    "outcome": "no_event",
    "code": "EPISODE_CONTINUES",
    "reason": "The same bad period is continuing; nothing new to say."
   },
   {
    "t": "11:50",
    "outcome": "no_event",
    "code": "EPISODE_CONTINUES",
    "reason": "The same bad period is continuing; nothing new to say."
   },
   {
    "t": "12:50",
    "outcome": "no_event",
    "code": "EPISODE_CONTINUES",
    "reason": "The same bad period is continuing; nothing new to say."
   },
   {
    "t": "13:50",
    "outcome": "no_event",
    "code": "EPISODE_CONTINUES",
    "reason": "The same bad period is continuing; nothing new to say."
   },
   {
    "t": "14:50",
    "outcome": "no_event",
    "code": "EPISODE_CONTINUES",
    "reason": "The same bad period is continuing; nothing new to say."
   },
   {
    "t": "15:50",
    "outcome": "no_event",
    "code": "EPISODE_CONTINUES",
    "reason": "The same bad period is continuing; nothing new to say."
   },
   {
    "t": "16:50",
    "outcome": "no_event",
    "code": "EPISODE_CONTINUES",
    "reason": "The same bad period is continuing; nothing new to say."
   },
   {
    "t": "17:50",
    "outcome": "no_event",
    "code": "EPISODE_CONTINUES",
    "reason": "The same bad period is continuing; nothing new to say."
   },
   {
    "t": "18:50",
    "outcome": "sent",
    "code": "SENT_CLEARED",
    "reason": "Sent: back to normal after a bad period."
   },
   {
    "t": "19:50",
    "outcome": "no_event",
    "code": "NO_TRIGGER",
    "reason": "Nothing unusual."
   }
  ],
  "night_utc": [
   {
    "utc": "2026-08-08T14:20:00Z",
    "code": "NO_TRIGGER"
   },
   {
    "utc": "2026-08-08T15:20:00Z",
    "code": "NO_TRIGGER"
   },
   {
    "utc": "2026-08-08T16:20:00Z",
    "code": "NO_TRIGGER"
   },
   {
    "utc": "2026-08-08T17:20:00Z",
    "code": "NO_TRIGGER"
   },
   {
    "utc": "2026-08-08T18:20:00Z",
    "code": "NO_TRIGGER"
   },
   {
    "utc": "2026-08-08T19:20:00Z",
    "code": "NO_TRIGGER"
   },
   {
    "utc": "2026-08-08T20:20:00Z",
    "code": "NO_TRIGGER"
   },
   {
    "utc": "2026-08-08T21:20:00Z",
    "code": "NO_TRIGGER"
   },
   {
    "utc": "2026-08-08T22:20:00Z",
    "code": "NO_TRIGGER"
   },
   {
    "utc": "2026-08-08T23:20:00Z",
    "code": "QUIET_HOURS_HELD"
   },
   {
    "utc": "2026-08-09T00:20:00Z",
    "code": "EPISODE_CONTINUES"
   },
   {
    "utc": "2026-08-09T01:00:00Z",
    "code": "SENT_CHECK_IN"
   },
   {
    "utc": "2026-08-09T01:20:00Z",
    "code": "DEDUP_SAME_BAND"
   },
   {
    "utc": "2026-08-09T02:20:00Z",
    "code": "DEDUP_SAME_BAND"
   },
   {
    "utc": "2026-08-09T03:20:00Z",
    "code": "DEDUP_SAME_BAND"
   },
   {
    "utc": "2026-08-09T04:20:00Z",
    "code": "DEDUP_SAME_BAND"
   },
   {
    "utc": "2026-08-09T05:20:00Z",
    "code": "EPISODE_CONTINUES"
   },
   {
    "utc": "2026-08-09T06:20:00Z",
    "code": "EPISODE_CONTINUES"
   },
   {
    "utc": "2026-08-09T07:20:00Z",
    "code": "EPISODE_CONTINUES"
   },
   {
    "utc": "2026-08-09T08:20:00Z",
    "code": "EPISODE_CONTINUES"
   },
   {
    "utc": "2026-08-09T09:20:00Z",
    "code": "EPISODE_CONTINUES"
   },
   {
    "utc": "2026-08-09T10:20:00Z",
    "code": "EPISODE_CONTINUES"
   },
   {
    "utc": "2026-08-09T11:20:00Z",
    "code": "EPISODE_CONTINUES"
   },
   {
    "utc": "2026-08-09T12:20:00Z",
    "code": "EPISODE_CONTINUES"
   },
   {
    "utc": "2026-08-09T13:20:00Z",
    "code": "SENT_CLEARED"
   },
   {
    "utc": "2026-08-09T14:20:00Z",
    "code": "NO_TRIGGER"
   }
  ]
 }
};
