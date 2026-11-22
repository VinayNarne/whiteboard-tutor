# Mindprint phase 0 v2: memory ceiling (note also in the lesson-plan request)

5 repeats, tutor and judge gpt-4.1-mini, raw `lesson_evals\2026-11-22-0027-memory-ceiling-v2.json`. Later sessions have 3 learner turns, scored over all replies plus board text (M3: first reply only). Session 1 reused from the earlier run. Every judge YES needs a verbatim quote found in the text, otherwise it is turned into NO.

| Measure | Session | off | oracle |
|---|---|---|---|
| M1 reteach DNS (YES=bad) | S2 | 5/5 | 5/5 |
| M1 reteach DNS (YES=bad) | S3 | 4/5 | 4/5 |
| M2 states DNS does not carry data (YES=good) | S2 | 0/5 | 5/5 |
| M2 states DNS does not carry data (YES=good) | S3 | 0/5 | 3/5 |
| M3 example first (YES=good) | S2 | 4/5 | 5/5 |
| M3 example first (YES=good) | S3 | 3/5 | 3/5 |
| M3 example first (YES=good) | S4 | 1/5 | 3/5 |
| M4 reuses analogy (YES=good) | S2 | 0/3 | 1/3 |
| M4 reuses analogy (YES=good) | S3 | 0/3 | 1/3 |
| M5 contradiction (YES=bad) | S2 | 0/5 | 0/5 |
| M5 contradiction (YES=bad) | S3 | 0/5 | 1/5 |

Quote downgrades (YES turned into NO): off 0, oracle 0.

## Per session

| Cond | Session | mean s/turn | mean blocks | non-200 turns |
|---|---|---|---|---|
| off | S2 | 6.4 | 3.4 | 0 |
| off | S3 | 5.8 | 3.8 | 0 |
| off | S4 | 6.9 | 4.2 | 0 |
| oracle | S2 | 6.2 | 3.8 | 0 |
| oracle | S3 | 5.6 | 4.0 | 0 |
| oracle | S4 | 6.3 | 4.0 | 0 |

## Lesson plan step titles

A step counts as a DNS-basics step when its title mentions DNS (or domain names) plus a what/how/works/lookup word and is not about spoofing or the misconception; read the titles to judge.

| Cond | Session | plans with a DNS-basics step |
|---|---|---|
| off | S2 | 5/5 |
| off | S3 | 1/5 |
| oracle | S2 | 4/5 |
| oracle | S3 | 4/5 |

- S2 off rep0: How DNS spoofing tricks browsers / Role of DNS in browsing / How attackers spoof DNS / Browser trusts DNS responses / Consequences of DNS spoofing / Recap card
- S2 off rep1: DNS spoofing tricks browsers / How DNS resolves domain names / How spoofing inserts false info / Effects on browser connections / How to detect and prevent spoofing
- S2 off rep2: What is DNS spoofing? / How DNS resolves domain names / How attackers spoof DNS responses / How browsers use DNS results / Preventing DNS spoofing
- S2 off rep3: DNS Spoofing Tricks Browsers / How DNS Resolves Domain Names / How Attackers Spoof DNS Responses / Browser Behavior on Spoofed DNS / Consequences of DNS Spoofing
- S2 off rep4: How DNS spoofing tricks browsers / Role of DNS in browsing / How attackers spoof DNS / Effects on users / Detecting spoofing
- S2 oracle rep0: What DNS spoofing does / How DNS queries work / How spoofing inserts fake answers / Why DNS is vulnerable / Correcting the DNS misconception / How HTTPS helps detect spoofing
- S2 oracle rep1: DNS Spoofing Tricks Your Browser / DNS Only Resolves Names to IPs / How Attackers Insert Fake DNS Data / Consequences of DNS Spoofing
- S2 oracle rep2: What DNS Spoofing Does / DNS Is Just a Phone Book / How Spoofing Happens / Consequences of Spoofing / Correcting DNS Misconception / Recap Card
- S2 oracle rep3: DNS spoofing tricks your browser / DNS only resolves names / How attackers send fake DNS responses / What happens after spoofing / How to protect against DNS spoofing
- S2 oracle rep4: What DNS spoofing does / How DNS queries work / How spoofing inserts fake answers / Correcting the DNS misconception / Why spoofing is dangerous / Recap card
- S3 off rep0: Email uses domain and DNS / Domain part identifies recipient’s domain / DNS translates domain to IP / MX records specify mail servers / Sending server connects to mail server / Recap card
- S3 off rep1: How email finds the mail server / Email address structure / DNS and MX records / SMTP connection / Recap card
- S3 off rep2: How email finds the mail server / Email address structure guides routing / DNS MX records specify mail servers / Sending server connects via SMTP / Recap card
- S3 off rep3: How email finds the mail server / Email address parts / DNS MX records explained / Sending server connects via SMTP / Handling multiple MX records / Recap card
- S3 off rep4: How email finds the mail server / Email address parts / MX record priority / Fallback to A record / SMTP connection / Recap card
- S3 oracle rep0: How email finds the mail server / What MX records are / DNS role vs routing / Connecting and sending email / Recap card
- S3 oracle rep1: How email finds the mail server / What MX records are / How DNS helps route email / What happens after DNS lookup / Recap card
- S3 oracle rep2: How email finds the mail server / What MX records are / DNS role vs routing / Sending email using SMTP / Recap card
- S3 oracle rep3: How email finds the mail server / What MX records are / DNS role vs data routing / Recap card
- S3 oracle rep4: How email finds the mail server / What MX records are / Resolving MX hostnames to IPs / Correcting the DNS misconception / Recap card

## S2 first replies, repeat 0

**off**: "DNS spoofing tricks your browser by feeding it fake IP addresses for websites, causing it to connect to malicious sites instead of the real ones. What do you think happens if your browser connects to a fake site that looks exactly like your bank's website?"

**oracle**: "The key moment in DNS spoofing is when a fake DNS reply tricks your browser into using a wrong IP address instead of the real one. What do you think might happen if your browser gets the wrong IP address for a website?"

## Spot-check

8 verdicts read against the text (rep, condition, session, measure, verdict): 
1. rep0 off S2 M1 YES: agree (board line 'translates domain names into IP addresses' plus a question about why the browser needs to translate).
2. rep1 oracle S3 M1 YES: agree, borderline (three-sentence MX lookup walk-through and a question about the DNS lookups).
3. rep0 oracle S2 M2 YES: agree (explicit 'DNS ... does not carry the actual website data or route your connection', quote verified in the text).
4. rep2 oracle S3 M2 NO: disagree, borderline (board says the message is sent by SMTP 'not DNS', which arguably counts as saying something else carries it).
5. rep0 off S3 M2 NO: agree.
6. rep3 oracle S4 M3 YES: disagree (the reply opens 'Here is how a hash table works...', and the board opens with a definition; no concrete example).
7. rep1 off S4 M3 NO: agree.
8. rep0 oracle S3 M5 YES: disagree (the quoted sentence, 'DNS only provides the IP address ... does not carry or route the email data', is consistent with the earlier explanation, not incompatible).
Agreement 5 of 8. Extra: the two M4 YES verdicts (rep2, phone book, S2 and S3) are real reuse, agree. M5 oracle S3 1/5 is a false positive; M3 is the loosest measure (counts a generic 'here is how' opening as an example, so treat M3 differences as weak).

Plan step titles read by hand: DNS-basics step ('Role of DNS in browsing', 'How DNS resolves domain names') in off S2 5/5 and off S3 1/5. Oracle S2: 2/5 have a full 'How DNS queries work' step; 3/5 replace it with a short 'DNS only resolves names' style step; 3 of 5 plans add 'Correcting the DNS misconception'. Oracle S3: 0/5 full DNS-basics steps (4/5 have a 'DNS role vs routing' or 'Correcting the DNS misconception' step, 5/5 have 'What MX records are'). The regex count in the table above over-counts these corrective steps.

