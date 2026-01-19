# Parallel Refinement Results

*Generated: 2026-01-15 03:11:59*

## Summary

| Metric | Value |
|--------|-------|
| Total Scenarios | 1 |
| Passed | 0 |
| Failed | 1 |
| Max Attempts | 2 |
| Total Duration | 396.7s |

## Scenario Results

| Scenario | Status | Attempts | Duration | Last Failure |
|----------|--------|----------|----------|-------------|
| search | FAIL | 2/2 | 396.7s | prompt 1 (high) |

## Failed Scenarios Detail

### search

- Attempt 1: FAIL at prompt 1 (quality: low)
- Attempt 2: FAIL at prompt 1 (quality: high)

## Retry Commands

```bash
make refine-skill SCENARIO=search MAX_ATTEMPTS=5
```
