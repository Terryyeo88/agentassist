# Reg 26/27 Fixture Review Worksheet

> **⚠️ DRAFT — ALL LABELS ARE UNTRUSTED UNTIL THIS WORKSHEET IS REVIEWED AND SIGNED OFF**
>
> These labels were machine-proposed by Claude Code on 2026-06-02.  They have NOT been verified
> by a human accountant against the IRAS source documents.  The recall and FP-rate claims derived
> from this fixture are **INVALID** until Terry and the accounting reviewer have completed this
> worksheet.  Do not promote `reg2627-labelled-lines.DRAFT.json` to `reg2627-labelled-lines.json`
> until every row has been reviewed and every `needs_human_review: true` cell has been decided.
>
> **Tuning rule:** If a proposed label is wrong, correct the label in the DRAFT file to match IRAS.
> Do **not** tune the knowledge-base slice or system prompt to make the model match a wrong label.
> Labels must reflect IRAS, not model behaviour.

---

## How to use this worksheet

1. Work through each row.  For rows with **Review needed = YES**, write your decision in the
   "Your decision" column (one of: flag / don't flag) and add a brief note.
2. For rows where the proposed label is simply wrong on the merits, cross it out and write the
   correct label.
3. When all rows are complete, update `reg2627-labelled-lines.DRAFT.json` to match your decisions.
4. Rename the file to `reg2627-labelled-lines.json` and update `_meta.ground_truth_set_by` to
   `"Terry Yeo — accounting review against IRAS sources, [date]"`.

---

## Section 1 — Club Subscriptions (proposed positives: 10)

| doc_num | line_idx | Description | Proposed candidate? | Proposed category | IRAS basis | Review needed? | Your decision |
|---------|----------|-------------|---------------------|-------------------|------------|----------------|---------------|
| 2001 | 0 | GOLF MBR RENEWAL | YES | club_subscriptions | §6.1.6 item 1 — annual golf club membership subscription disallowed | No | |
| 2002 | 0 | CLUB JOINING FEE | YES | club_subscriptions | §6.1.6 item 1 — joining fee disallowed | No | |
| 2003 | 0 | MBR TRANSFER FEE | YES | club_subscriptions | §6.1.6 item 1 — transfer fee disallowed | No | |
| 2004 | 0 | NSRCC MBR SUBS | YES | club_subscriptions | §6.1.6 item 1 — subscription to recreational club disallowed | No | |
| 2005 | 0 | SAFRA SWIM CLUB SUBS | YES | club_subscriptions | §6.1.6 item 1 — subscription to sporting club disallowed | No | |
| 2006 | 0 | TENNIS CLUB ANNUAL FEE | YES | club_subscriptions | §6.1.6 item 1 — annual fee to sporting club disallowed | No | |
| 2007 | 0 | REC CLUB ANNUAL MBR | YES | club_subscriptions | §6.1.6 item 1 — recreational club annual membership disallowed | No | |
| 2008 | 0 | SPORTS CLUB MBR FEE | YES | club_subscriptions | §6.1.6 item 1 — membership fee to sporting club disallowed | No | |
| 2009 | 0 | RCYC MBR SUBS | YES | club_subscriptions | §6.1.6 item 1 — yacht club subscription disallowed | No | |
| 2010 | 0 | POLO CLUB MBR RENEWAL | YES | club_subscriptions | §6.1.6 item 1 — polo club membership renewal disallowed | No | |

---

## Section 2 — Medical Expenses (proposed positives: 11)

> **Methodology note for WICA lines:** IRAS §6.1.6 item 2 disallows medical expenses UNLESS they
> are mandatory under WICA or under a collective agreement (IRA), or are work-environment health
> requirements (post-Oct 2021).  For terse SAP descriptions where the statutory basis is unknown,
> the **conservative/recall-preserving** approach is to **flag** (proposed candidate = YES).
> If your firm's policy is to flag every ambiguous "STAFF MEDICAL" line for reviewer attention,
> set expected_candidate = true.  If you treat ambiguous lines as claimable by default (because
> the employer must prove WICA status), set expected_candidate = false.  Record your methodology
> call in the "Your decision" column — this decision must be consistent across all similar lines.

| doc_num | line_idx | Description | Proposed candidate? | Proposed category | IRAS basis | Review needed? | Your decision |
|---------|----------|-------------|---------------------|-------------------|------------|----------------|---------------|
| 2011 | 0 | STAFF MED CHECKUP | YES | medical_expenses | §6.1.6 item 2 — medical expense; WICA status unknown | **YES** | |
| 2012 | 0 | VOLUNTARY HEALTH SCREEN | YES | medical_expenses | §6.1.6 item 2 — voluntary (non-statutory) health screening | No | |
| 2013 | 0 | STAFF DENTAL TREAT | YES | medical_expenses | §6.1.6 item 2 — dental treatment; WICA status unknown | **YES** | |
| 2014 | 0 | GP CONSULT STAFF | YES | medical_expenses | §6.1.6 item 2 — GP consultation; WICA status unknown | **YES** | |
| 2015 | 0 | SPECIALIST CONSULT STAFF | YES | medical_expenses | §6.1.6 item 2 — specialist consultation; WICA unknown | **YES** | |
| 2016 | 0 | STAFF HOSPITALISE | YES | medical_expenses | §6.1.6 item 2 — hospitalisation; WICA/work-injury unknown | **YES** | |
| 2017 | 0 | TCM TREAT STAFF | YES | medical_expenses | §6.1.6 item 2 — TCM treatment; no WICA exception for TCM | No | |
| 2018 | 0 | HEALTH SCREEN 15 PAX | YES | medical_expenses | §6.1.6 item 2 — health screening; WICA status unknown | **YES** | |
| 2019 | 0 | GRP MED INS PREM | YES | medical_expenses | §6.1.6 item 3 — group medical insurance; WICA mandatory status unknown | **YES** | |
| 2019 | 1 | PA INS STAFF | YES | medical_expenses | §6.1.6 item 3 — personal accident insurance; WICA mandatory unknown | **YES** | |
| 2020 | 0 | EYE TEST STAFF | YES | medical_expenses | §6.1.6 item 2 — eye test; work-environment exception possible but unclear | **YES** | |

---

## Section 3 — Motor Car S-Plate (proposed positives: 11)

| doc_num | line_idx | Description | Proposed candidate? | Proposed category | IRAS basis | Review needed? | Your decision |
|---------|----------|-------------|---------------------|-------------------|------------|----------------|---------------|
| 2021 | 0 | PETROL S-PLATE | YES | motor_car_s_plate | §6.1.6 item 5 — petrol for S-plate car disallowed | No | |
| 2022 | 0 | CAR WASH S-PLATE | YES | motor_car_s_plate | §6.1.6 item 5 — car wash on S-plate is running expense | No | |
| 2023 | 0 | SEASON PKG S-PLATE | YES | motor_car_s_plate | §5.13(n) — parking on S-plate car disallowed | No | |
| 2024 | 0 | S-PLATE CAR SVC | YES | motor_car_s_plate | §6.1.6 item 5 — service/maintenance on S-plate disallowed | No | |
| 2025 | 0 | CAR RENTAL POST-JUL99 | YES | motor_car_s_plate | §5.13(n) — rental car hired for use on/after 1 Jul 1999 | No | |
| 2026 | 0 | COE RENEWAL CO CAR | YES | motor_car_s_plate | §5.13(n) — company car COE renewed on/after 1 Apr 1998 | No | |
| 2027 | 0 | CAR INS S-PLATE | YES | motor_car_s_plate | §6.1.6 item 5 — insurance on S-plate car is running expense | No | |
| 2028 | 0 | RD TAX S-PLATE | YES | motor_car_s_plate | §6.1.6 item 5 — road tax on S-plate car is running expense | No | |
| 2029 | 0 | BODYWORK S-PLATE | YES | motor_car_s_plate | §6.1.6 item 5 — repair on S-plate car disallowed | No | |
| 2030 | 0 | CARPARK SEASON S-PLATE SN | YES | motor_car_s_plate | §5.13(n) — parking on S-plate car disallowed | No | |
| 2031 | 0 | PRIV CAR LEASE MTH | YES | motor_car_s_plate | §6.1.6 item 5 — monthly lease of private motor car disallowed | No | |

---

## Section 4 — Family Benefits (proposed positives: 10)

| doc_num | line_idx | Description | Proposed candidate? | Proposed category | IRAS basis | Review needed? | Your decision |
|---------|----------|-------------|---------------------|-------------------|------------|----------------|---------------|
| 2032 | 0 | SPOUSE TRAVEL EXP | YES | family_benefits | §6.1.6 item 4 — travel benefit for spouse of staff | No | |
| 2033 | 0 | DIR FAMILY HOLIDAY | YES | family_benefits | §6.1.6 item 4 — family holiday benefit disallowed | No | |
| 2034 | 0 | CHILD TUITION STAFF | YES | family_benefits | §6.1.6 item 4 — tuition benefit for child of staff | No | |
| 2035 | 0 | SPOUSE CLUB MBR | YES | family_benefits | §6.1.6 item 4 — club membership for spouse disallowed | No | |
| 2036 | 0 | FAMILY MED STAFF | YES | family_benefits | §6.1.6 item 4 — medical for family member of staff | No | |
| 2037 | 0 | DIR SPOUSE BDAY DIN | YES | family_benefits | §6.1.6 item 4 — private dining for spouse of director | No | |
| 2038 | 0 | STAFF FAMILY TRAVEL | YES | family_benefits | §6.1.6 item 4 — travel benefit for family of staff | No | |
| 2039 | 0 | CHILD ENRICHMENT | YES | family_benefits | §6.1.6 item 4 — enrichment benefit for child of staff | No | |
| 2040 | 0 | SPOUSE DENTAL STAFF | YES | family_benefits | §6.1.6 item 4 — dental benefit for spouse of staff | No | |
| 2041 | 0 | FAMILY GIFT ALLOW | YES | family_benefits | §6.1.6 item 4 — gift allowance for family of staff | No | |

---

## Section 5 — Entertainment (proposed positives: 11)

> **Methodology note:** IRAS KB §EXCEPTIONS-1 states that food/drink for **internal staff** is
> generally claimable (simplified tax invoice route).  Only entertainment of **external parties**
> (clients, guests, prospects, vendors) is disallowed.  Lines with an explicit external party
> reference (CLIENT, GUEST, PROSPECT, CUSTOMER) are marked as positive.  Lines where the external
> nature is ambiguous are marked `needs_human_review`.

| doc_num | line_idx | Description | Proposed candidate? | Proposed category | IRAS basis | Review needed? | Your decision |
|---------|----------|-------------|---------------------|-------------------|------------|----------------|---------------|
| 2042 | 0 | CLIENT DIN ENTMT | YES | entertainment | Reg 26(1)(a) — entertainment of external client | No | |
| 2043 | 0 | YACHT CHARTER CLIENT | YES | entertainment | Reg 26(1)(a); §6.1.3(b)(ii) — yacht charter for client | No | |
| 2044 | 0 | GOLF CLIENT GUEST | YES | entertainment | Reg 26(1)(a) — golf for external client guest | No | |
| 2045 | 0 | KARAOKE CLIENT ENTMT | YES | entertainment | Reg 26(1)(a) — karaoke entertainment for client | No | |
| 2046 | 0 | CORP BOX SPORTS EVT | YES | entertainment | Reg 26(1)(a) — corporate hospitality box for external parties | No | |
| 2047 | 0 | CUST HOSP DINNER | YES | entertainment | Reg 26(1)(a) — customer hospitality dinner | No | |
| 2048 | 0 | BIZ LUNCH EXT GUEST | YES | entertainment | Reg 26(1)(a) — business lunch with external guest stated | No | |
| 2049 | 0 | PROSPECT DINNER | YES | entertainment | Reg 26(1)(a) — dinner for sales prospect | No | |
| 2050 | 0 | CLIENT CRUISE ENTMT | YES | entertainment | Reg 26(1)(a) — cruise entertainment for clients | No | |
| 2051 | 0 | VENDOR APPREC DIN | YES | entertainment | Reg 26(1)(a) — vendor appreciation dinner; external vendor assumed | **YES** | |
| 2052 | 0 | PROD LAUNCH GALA EXT | YES | entertainment | Reg 26(1)(a) — gala with external guests indicated | No | |

---

## Section 6 — Other Disallowed (proposed positives: 10)

| doc_num | line_idx | Description | Proposed candidate? | Proposed category | IRAS basis | Review needed? | Your decision |
|---------|----------|-------------|---------------------|-------------------|------------|----------------|---------------|
| 2053 | 0 | TOTO SYS BET | YES | other_disallowed | §6.1.6 item 6 — TOTO (lottery) transaction disallowed | No | |
| 2054 | 0 | FOOTBALL BET | YES | other_disallowed | §6.1.6 item 6 — betting transaction disallowed | No | |
| 2055 | 0 | 4D LOTTERY TKT | YES | other_disallowed | §6.1.6 item 6 — lottery transaction disallowed | No | |
| 2056 | 0 | CASINO CHIPS | YES | other_disallowed | §6.1.6 item 6 — game of chance (casino) transaction | No | |
| 2057 | 0 | FRUIT MACH SVC CONTR | YES | other_disallowed | §6.1.6 item 6 — transaction involving fruit machines | No | |
| 2058 | 0 | SWEEP TKT CHARITY | YES | other_disallowed | §6.1.6 item 6 — sweepstakes transaction disallowed | No | |
| 2059 | 0 | LUCKY DRAW TKT | YES | other_disallowed | §6.1.6 item 6 — lottery/game of chance transaction | No | |
| 2060 | 0 | HORSE RACING BET | YES | other_disallowed | §6.1.6 item 6 — betting transaction disallowed | No | |
| 2061 | 0 | SCRATCH CARD BULK | YES | other_disallowed | §6.1.6 item 6 — lottery (scratch card) transaction | No | |
| 2062 | 0 | ONLINE BETTING | YES | other_disallowed | §6.1.6 item 6 — betting transaction disallowed | No | |

---

## Section 7 — Negatives: Commercial Vehicles (proposed: 10)

> **These are the HARD false-positive discipline cases.**  A model that over-flags "motor car"
> expenses will flag these.  The correct answer is NOT A CANDIDATE because goods vehicles,
> motorcycles, and buses are outside the Reg 25(1) "motor car" definition.  However, bare "VAN"
> or "FLEET VAN" without vehicle-type confirmation requires reviewer judgment.

| doc_num | line_idx | Description | Proposed candidate? | Proposed category | IRAS basis | Review needed? | Your decision |
|---------|----------|-------------|---------------------|-------------------|------------|----------------|---------------|
| 2063 | 0 | LORRY SVC 30K KM | **NO** | — | §EXCEPTIONS-2 KB — lorry (goods vehicle) outside Reg 25(1) | No | |
| 2064 | 0 | VAN DIESEL FLEET | **NO** | — | §EXCEPTIONS-2 KB — delivery van (goods vehicle) outside Reg 25(1) | No | |
| 2065 | 0 | TRUCK TYRE REPL | **NO** | — | §EXCEPTIONS-2 KB — commercial truck outside Reg 25(1) | No | |
| 2066 | 0 | FORKLIFT SVC CONTR | **NO** | — | §EXCEPTIONS-2 KB — forklift is industrial equipment, not Reg 25(1) | No | |
| 2067 | 0 | MOTORCYCLE FUEL | **NO** | — | §EXCEPTIONS-2 KB — motorcycle outside Reg 25(1) | No | |
| 2068 | 0 | BUS CHARTER STAFF | **NO** | — | §EXCEPTIONS-2 KB — bus outside Reg 25(1) | No | |
| 2069 | 0 | TIPPER TRUCK RPR | **NO** | — | §EXCEPTIONS-2 KB — tipper truck (goods vehicle) outside Reg 25(1) | No | |
| 2070 | 0 | VAN CARPARK SEASON | **NO** | — | §EXCEPTIONS-2 KB — van assumed goods vehicle; type ambiguous | **YES** | |
| 2071 | 0 | DELIVERY VAN INS | **NO** | — | §EXCEPTIONS-2 KB — delivery van (goods vehicle) insurance claimable | No | |
| 2072 | 0 | FLEET VAN BODY RPR | **NO** | — | §EXCEPTIONS-2 KB — fleet van (goods vehicle assumed); type ambiguous | **YES** | |

---

## Section 8 — Negatives: WICA / Statutory Medical (proposed: 6)

> **Methodology note:** Lines explicitly labelled "WICA", "WSH", or "MANDATORY" in the description
> are proposed as negative (claimable under the exception).  Lines where the statutory basis is
> ambiguous but the description implies work-related injury/health are also proposed negative with
> `needs_human_review: true`.  Confirm that your firm's convention matches.

| doc_num | line_idx | Description | Proposed candidate? | Proposed category | IRAS basis | Review needed? | Your decision |
|---------|----------|-------------|---------------------|-------------------|------------|----------------|---------------|
| 2073 | 0 | WICA MED EXAM MAND | **NO** | — | §6.1.6 item 2(a) — mandatory WICA exam; exception stated | No | |
| 2074 | 0 | WORK INJURY TREAT | **NO** | — | §6.1.6 item 2(a) — work injury; WICA eligibility assumed, unconfirmed | **YES** | |
| 2075 | 0 | WSH MEDICAL EXAM | **NO** | — | §6.1.6 item 2(a)/(b) — WSH regulatory exam; exception applies | No | |
| 2076 | 0 | OCC HEALTH SCREEN | **NO** | — | §6.1.6 item 2(b) — occupational health; post-Oct 2021 exception likely | **YES** | |
| 2077 | 0 | WICA INS PREM | **NO** | — | §6.1.6 item 3 — WICA-mandatory insurance; exception stated | No | |
| 2078 | 0 | WORK INJURY COMP INS | **NO** | — | §6.1.6 item 3 — WICA compensation insurance; exception applies | No | |

---

## Section 9 — Negatives: Work-Environment Health (proposed: 3)

| doc_num | line_idx | Description | Proposed candidate? | Proposed category | IRAS basis | Review needed? | Your decision |
|---------|----------|-------------|---------------------|-------------------|------------|----------------|---------------|
| 2079 | 0 | CHEM EXPOSURE TEST | **NO** | — | §6.1.6 item 2(b)(i) — WSH chemical health test; exception applies | No | |
| 2080 | 0 | HEARING TEST OCC | **NO** | — | §6.1.6 item 2(b)(i) — WSH noise regulations hearing test | No | |
| 2081 | 0 | RADIATION HEALTH MON | **NO** | — | §6.1.6 item 2(b)(i) — Radiation Protection Act requirement | No | |

---

## Section 10 — Negatives: Internal Staff Meals / Welfare (proposed: 5)

| doc_num | line_idx | Description | Proposed candidate? | Proposed category | IRAS basis | Review needed? | Your decision |
|---------|----------|-------------|---------------------|-------------------|------------|----------------|---------------|
| 2082 | 0 | STAFF CANTEEN F&B | **NO** | — | §EXCEPTIONS-1 KB — internal staff canteen; claimable | No | |
| 2083 | 0 | TEAM LUNCH INTERNAL | **NO** | — | §EXCEPTIONS-1 KB — internal team lunch; claimable | No | |
| 2084 | 0 | STAFF DINNER ALL HANDS | **NO** | — | §EXCEPTIONS-1 KB — if all internal; but "all hands" may include external | **YES** | |
| 2085 | 0 | OFFICE REFRESH WEEKLY | **NO** | — | §EXCEPTIONS-1 KB — office refreshments for staff; claimable | No | |
| 2086 | 0 | STAFF BDAY CAKE | **NO** | — | §EXCEPTIONS-1 KB — internal staff welfare; claimable | No | |

---

## Section 11 — Negatives: Business Insurance (proposed: 4)

| doc_num | line_idx | Description | Proposed candidate? | Proposed category | IRAS basis | Review needed? | Your decision |
|---------|----------|-------------|---------------------|-------------------|------------|----------------|---------------|
| 2087 | 0 | FIRE INS FACTORY | **NO** | — | §EXCEPTIONS-5 KB — fire/property insurance; not Reg 27 item 3 | No | |
| 2088 | 0 | PROD LIAB INS | **NO** | — | §EXCEPTIONS-5 KB — product liability; not staff medical/accident insurance | No | |
| 2089 | 0 | D&O INS PREM | **NO** | — | §EXCEPTIONS-5 KB — D&O governance insurance; not Reg 27 item 3 | No | |
| 2090 | 0 | MARINE CARGO INS | **NO** | — | §EXCEPTIONS-5 KB — marine cargo insurance; not Reg 27 item 3 | No | |

---

## Section 12 — Negatives: Ordinary Business Expenses (proposed: 19)

| doc_num | line_idx | Description | Proposed candidate? | Proposed category | IRAS basis | Review needed? | Your decision |
|---------|----------|-------------|---------------------|-------------------|------------|----------------|---------------|
| 2091 | 0 | OFFICE SUPPLIES MISC | **NO** | — | No Reg 26/27 category — office consumables | No | |
| 2092 | 0 | PRINTING PAPER 10RMS | **NO** | — | No Reg 26/27 category — printing consumables | No | |
| 2093 | 0 | SOFTWARE LIC ANN | **NO** | — | No Reg 26/27 category — software licence | No | |
| 2094 | 0 | CLOUD SVC HOST | **NO** | — | No Reg 26/27 category — cloud hosting | No | |
| 2095 | 0 | RAW MATERIAL STEEL | **NO** | — | No Reg 26/27 category — production raw material | No | |
| 2096 | 0 | FREIGHT FWD AIRFREIGHT | **NO** | — | No Reg 26/27 category — freight forwarding | No | |
| 2097 | 0 | COURIER SVC LOCAL | **NO** | — | No Reg 26/27 category — local courier | No | |
| 2098 | 0 | EQUIP REPAIR MACHINE | **NO** | — | No Reg 26/27 category — machinery repair | No | |
| 2099 | 0 | FACTORY MAINT ANN | **NO** | — | No Reg 26/27 category — factory maintenance | No | |
| 2100 | 0 | AUDIT FEE | **NO** | — | No Reg 26/27 category — audit professional fee | No | |
| 2101 | 0 | LEGAL FEE CORP | **NO** | — | No Reg 26/27 category — corporate legal fee | No | |
| 2102 | 0 | DIGITAL ADV CAMPAIGN | **NO** | — | No Reg 26/27 category — advertising spend | No | |
| 2103 | 0 | STAFF TRAINING COURSE | **NO** | — | No Reg 26/27 category — staff training | No | |
| 2104 | 0 | SUNDRY | **NO** | — | Cannot determine from description — reviewer must inspect invoice | **YES** | |
| 2105 | 0 | MISC | **NO** | — | Cannot determine from description — reviewer must inspect invoice | **YES** | |
| 2106 | 0 | PACKING MATERIAL | **NO** | — | No Reg 26/27 category — production consumable | No | |
| 2107 | 0 | ELECTRICITY BILL | **NO** | — | No Reg 26/27 category — utility | No | |
| 2108 | 0 | INTERNET SVC | **NO** | — | No Reg 26/27 category — IT/comms | No | |
| 2109 | 0 | PRINT STAT SUPPLIES | **NO** | — | No Reg 26/27 category — stationery | No | |

---

## Sign-off

Once all rows above have been reviewed:

- [ ] All labels confirmed or corrected against IRAS source documents
- [ ] Methodology call for WICA-ambiguous medical lines documented and applied consistently
- [ ] VAN/fleet vehicle lines reviewed against actual vehicle registration records
- [ ] SUNDRY / MISC labels confirmed (inspect underlying invoices)
- [ ] DRAFT file updated to match all corrections
- [ ] `_meta.ground_truth_set_by` updated to `"Terry Yeo — accounting review against IRAS sources, YYYY-MM-DD"`
- [ ] File renamed from `reg2627-labelled-lines.DRAFT.json` to `reg2627-labelled-lines.json`
- [ ] Recall / FP-rate measurement run and gate decision recorded

**Reviewer:** ______________________  **Date:** _______________

**Accounting sign-off:** ______________________  **Date:** _______________
