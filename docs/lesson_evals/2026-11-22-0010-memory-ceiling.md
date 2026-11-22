# Mindprint phase 0: memory ceiling

5 repeats, gpt-4.1-mini tutor and judge, raw data `lesson_evals\2026-11-22-0010-memory-ceiling.json`. off = no memory, oracle = hand-written note before the learner's message.
YES counts out of runs judged (M4 only where an analogy was found in session 1).

| Measure | Session | off | oracle |
|---|---|---|---|
| M1 reteach DNS (YES=bad) | S2 | 5/5 | 3/5 |
| M1 reteach DNS (YES=bad) | S3 | 0/5 | 1/5 |
| M2 corrects misconception (YES=good) | S2 | 4/5 | 1/5 |
| M2 corrects misconception (YES=good) | S3 | 3/5 | 5/5 |
| M3 example first (YES=good) | S2 | 4/5 | 5/5 |
| M3 example first (YES=good) | S3 | 2/5 | 3/5 |
| M3 example first (YES=good) | S4 | 0/5 | 1/5 |
| M4 reuses analogy (YES=good) | S2 | 0/3 | 0/3 |
| M4 reuses analogy (YES=good) | S3 | 0/3 | 0/3 |
| M5 contradiction (YES=bad) | S2 | 3/5 | 3/5 |
| M5 contradiction (YES=bad) | S3 | 2/5 | 2/5 |

## Per session cost and failures

| Cond | Session | mean s/turn | mean blocks/session | non-200 turns |
|---|---|---|---|---|
| off | S2 | 5.9 | 3.4 | 0 |
| off | S3 | 6.0 | 2.4 | 0 |
| off | S4 | 8.3 | 3.8 | 0 |
| oracle | S2 | 6.2 | 3.0 | 0 |
| oracle | S3 | 6.6 | 3.0 | 0 |
| oracle | S4 | 6.8 | 2.8 | 0 |

Session 1 (5 runs): mean 5.5 s/turn, non-200 turns 0.
Analogies found: Domain names as human-friendly labels vs IP addresses; NONE; Phone book analogy for DNS lookup; NONE; Domain names are like easy-to-remember words

## S2 first reply, repeat 0

**off**: "DNS spoofing tricks your browser by giving a fake IP address for a website name, so your browser connects to a malicious site instead of the real one. Why do you think it is dangerous if your browser connects to a fake website that looks like the real one?"

**oracle**: "DNS spoofing tricks your browser by sending fake DNS replies. The attacker intercepts your browser's request to DNS for a website's IP and sends back a wrong IP address. Then your browser connects to that wrong IP, which is often a fake server that can steal your data or show fake pages. Why would an attacker want your browser to connect to a fake server instead of the real one?"

## Spot-check

I read 6 verdicts against the reply and board text (all in the raw json): M2 S2 oracle rep0 NO (agree, no statement that DNS does not carry data), M4 S3 oracle rep2 NO (agree, no phone-book mention), M5 S2 oracle rep0 NO (agree), M1 S3 oracle rep1 NO (agree, only a one-line mention of DNS), M3 S4 oracle rep0 NO (agree, board opens with a definition), M2 S3 oracle rep4 YES (disagree: the reply only says DNS looks up the MX record; it never says DNS does not carry the data, so the judge was lenient). 5 of 6 agree; the judge leans lenient on YES for M2.

## Caveats

- Session 1 produced an analogy in 3 of 5 runs, and two of those ("human-friendly labels", "easy-to-remember words") are weak comparisons; M4 is judged on 3 runs per cell only.
- Earlier smoke-test json files (2026-11-22-0003, -0005 and one S4-only run) remain in this folder; the 5-repeat file is 2026-11-22-0010.
- One judge (gpt-4.1-mini, temperature 0), 5 runs per cell: differences of 1-2 are noise.
