# Alloy to Pyroscope profiling spike (2026-11-12)

Setup: LXD VM `alloy-spike` (ubuntu 24.04), gotodo v0.1.0 with `OPS_ADDR=127.0.0.1:6060`, Pyroscope 1.21.0 (apt `pyroscope=1.21.0`, `:4040`), Alloy from apt.grafana.com (same repo as `alloy.py:install`). 15s scrape interval, about 10 minutes of register/login/create-todo load.

## Profile type IDs

Series present for `service_name="gotodo"` (11 types):

```
block:contentions:count:contentions:count
block:delay:nanoseconds:contentions:count
goroutine:goroutine:count:goroutine:count
memory:alloc_objects:count:space:bytes
memory:alloc_space:bytes:space:bytes
memory:inuse_objects:count:space:bytes
memory:inuse_space:bytes:space:bytes
mutex:contentions:count:contentions:count
mutex:delay:nanoseconds:contentions:count
process_cpu:cpu:nanoseconds:cpu:nanoseconds
process_cpu:samples:count:cpu:nanoseconds
```

Notes:
- godeltaprof_memory/mutex/block are ingested under the same `memory:*`, `mutex:*`, `block:*` IDs as the plain endpoints. There is no `godeltaprof` prefix in the IDs.
- The goroutine ID is `goroutine:goroutine:count:goroutine:count`. (`goroutines:goroutine:count:goroutine:count` also exists globally, but only from Pyroscope's own self-profiling, `service_name=pyroscope`.)
- `gotodo-plain` has the 8 memory/mutex/block IDs only. The global ProfileTypes call (no filter) returns the union plus the pyroscope self-profile types.

## instance label

Kept as `gotodo/0`. `LabelValues{name:"instance"}` returned `["gotodo/0"]` (also when filtered to `service_name="gotodo"`). Alloy did not overwrite it, so Task 3 Step 3 does not need the relabel variant. `service_name` values seen: `gotodo`, `gotodo-plain`, `pyroscope`.

## Cumulative endpoints (gotodo-plain)

Flat, not growing. SelectSeries (30s step, summed) for `service_name="gotodo-plain"`; scrape started about 22:05, so minute 2 is about 22:07 and minute 10 about 22:15:

| type | minute 2 (22:07:13) | minute 10 (22:15:14) |
|---|---|---|
| `memory:alloc_space` (bytes) | 27,212,368 | 17,082,570 |
| `mutex:delay` (ns) | 90,325 | 3,912,706 |
| `block:delay` (ns) | 28,570,238,462 | 28,545,615,366 |

Whole series 22:06 to 22:15: `alloc_space` stayed between 15M and 27M, `block:delay` stayed at about 28.3 to 28.7e9 (after the first partial bucket), `mutex:delay` was noisy (14k to 3.9M, with no monotonic trend). Compare `gotodo` (godeltaprof) alloc_space, 5.6M to 15M per step. Under steady load the plain values do not accumulate; the gate passes. Caveat: `mutex:delay` is spiky, so dashboards should use rate or per-step views rather than expecting smooth values.

## Alloy version

```
alloy, version v1.21.3 (branch: HEAD, revision: f2108cd)
  build user:       root@eb0633faf47d
  build date:       2026-10-28T16:58:58Z
```

Pyroscope: `pyroscope, version 1.21.0 (branch: HEAD, revision: 9cd4ab0a1)` (1.21.0 was available as an exact apt version).

## Working config.alloy

Accepted block names under `profiling_config`: `profile.process_cpu`, `profile.godeltaprof_memory`, `profile.godeltaprof_mutex`, `profile.godeltaprof_block`, `profile.goroutine`, `profile.memory`, `profile.mutex`, `profile.block`, `profile.fgprof`. REJECTED: `profile.go_goroutines_golang_org` ("unrecognized block name"; I had guessed it, and it is not needed). Note `alloy fmt` passed even with that bad block; only the real load (`journalctl -u alloy`) caught it, so later tasks should validate with `alloy run`/service start, not just `alloy fmt`. Also, apt installs Alloy enabled and starts it, so a bad config at first start causes a restart loop; use `systemctl reset-failed alloy` before restarting.

```alloy
pyroscope.write "pyroscope" {
  endpoint {
    url = "http://127.0.0.1:4040"
  }
}

pyroscope.scrape "gotodo" {
  targets = [
    {"__address__" = "127.0.0.1:6060", "service_name" = "gotodo", "instance" = "gotodo/0"},
  ]
  forward_to      = [pyroscope.write.pyroscope.receiver]
  scrape_interval = "15s"

  profiling_config {
    profile.process_cpu {
      enabled = true
    }
    profile.godeltaprof_memory {
      enabled = true
    }
    profile.godeltaprof_mutex {
      enabled = true
    }
    profile.godeltaprof_block {
      enabled = true
    }
    profile.goroutine {
      enabled = true
    }
    profile.memory {
      enabled = false
    }
    profile.mutex {
      enabled = false
    }
    profile.block {
      enabled = false
    }
    profile.fgprof {
      enabled = false
    }
  }
}

pyroscope.scrape "gotodo_plain" {
  targets = [
    {"__address__" = "127.0.0.1:6060", "service_name" = "gotodo-plain", "instance" = "gotodo/0"},
  ]
  forward_to      = [pyroscope.write.pyroscope.receiver]
  scrape_interval = "15s"

  profiling_config {
    profile.process_cpu {
      enabled = false
    }
    profile.godeltaprof_memory {
      enabled = false
    }
    profile.godeltaprof_mutex {
      enabled = false
    }
    profile.godeltaprof_block {
      enabled = false
    }
    profile.goroutine {
      enabled = false
    }
    profile.memory {
      enabled = true
    }
    profile.mutex {
      enabled = true
    }
    profile.block {
      enabled = true
    }
    profile.fgprof {
      enabled = false
    }
  }
}
```
