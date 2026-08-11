# Anthropic Messages Loop → ThinHarness 0.6.0

## Scope

Ši migracija pakeičia tik `ranker.py` LLM vykdymo seam: rank_jobs/score_job/preflight vieši kontraktai, Playwright scraping, deduplikacija, agregavimas, formalus rezultato kontraktas, grounding/downgrade, prompt-injection taisyklės ir safe fallback lieka tie patys. `config.CLAUDE_MODEL` default dabar yra provider-qualified `anthropic:claude-sonnet-4-6`.

## Before / After

| Sritis | Prieš | Po |
|---|---|---|
| Agent loop | Ranker ranka siuntė Anthropic Messages turns ir jungė `tool_use`/`tool_result` | Fresh `Harness` kiekvienam darbui; ThinHarness valdo turns ir tool vykdymą |
| Modelis | Tiesioginis `anthropic.Anthropic` globalus klientas | ThinHarness provider-qualified model ref; `ANTHROPIC_API_KEY` env lieka |
| Įrankiai | Anthropic dict schema + `_execute_tool` dispatcher | Vienas per-job Pydantic `ToolSpec`; `builtin_tools=[]` |
| SSRF | `_execute_tool` ignoravo modelio input ir naudojo expected URL | Empty args model ignoruoja extra laukus; handler closure turi tik programinį job URL |
| Išvestis | Teksto fence strip + `json.loads` + `_validate_schema` | Anthropic native structured output + `RankResponse` + `output_retries=2` |
| Score | `int` ir app-side clamp 0–10 | Tas pats app-side clamp; out-of-range score nėra output retry |
| Papildomi sąrašai | `_coerce_string_list` priėmė netvarkingus/numerinius list elementus | RankResponse laukai permissive; tas pats `_coerce_string_list` |
| Grounding | title/company/snippet + sėkmingi tool tekstai | Tas pats `seen_text` turinys ir tas pats substring/fuzzy check |
| Tool klaida | `is_error=True` buvo grąžinamas modeliui, loop tęsėsi | Handler exception tampa failed `ToolResult`; `tool_retries=0`, sesija tęsiasi |
| Transient retry | Tenacity kartojo vieną Anthropic SDK request, išlaikydamas pokalbį | ThinHarness pakartoja tą patį provider request tame pačiame pokalbyje; `request_retries=2` |
| Preflight | Tiesioginis vieno tokeno SDK ping | Vieno request'o, no-tools ThinHarness run, tas pats `(ok, error)` |
| Tracing | Aplikacija nerašė pilnų promptų trace | `local_tracing=False`, kad CV/prompt/tool tekstai nebūtų rašomi į `~/.thinharness/traces` |
| Dependency | `anthropic>=0.34` | `thinharness==0.6.0` ir Pydantic 2; tiesioginio Anthropic SDK plumbing nebėra |

## Capacity

Default scoring run naudoja `temperature=0`, `max_tokens=1024`, `request_retries=2`, `max_model_requests=5`, `max_tool_calls=3`, `output_retries=2`, `tool_retries=0`. Du provider retry pakeičia aplikacijos aiškią trijų bandymų Tenacity taisyklę. Penki modelio request'ai leidžia tool turns ir structured-output pataisymus. Trijų tool call riba riboja modelio veiksmus. `score_job(..., max_iterations=...)` argumentas lieka viešame kontrakte. Teigiama nestandartinė reikšmė nustato modelio request ribą. Tool riba yra mažesnė iš šios reikšmės ir `MAX_TOOL_CALLS=3`.

## Intentional differences

1. **Provider retry implementacija pasikeitė, semantika išliko.** ThinHarness 0.6.0 kartoja connection/timeout, 408, 409, 425, 429 ir 5xx provider request tame pačiame pokalbyje. Jau užbaigti tool call nekartojami. Auth, permission ir kitos non-retryable 4xx klaidos nekartojamos. Testai vykdo `score_job()` su realiu ThinHarness Anthropic provider ir `httpx.MockTransport`.
2. **Schema klaidos taisomos.** Trūkstamas privalomas laukas, tuščias reason, blogas evidence tipas ar ne JSON tekstas gauna iki dviejų corrective retries. Anksčiau kai kurios schema klaidos iškart tapdavo `score=0`; parse klaidos dalinosi trijų rankinio loop iteracijų kvotą.
3. **Request accounting pasikeitė.** `model_requests` ir `tool_calls` imami iš viešo `run_end` hook usage. Provider transporto retry nėra atskirai įtraukiami. Galutinai nepavykęs provider request aproksimuojamas kaip vienas request, nors transporto bandymų gali būti trys. Manifestas rodo loginį darbą, bet Anthropic Console lieka billing source of truth.
4. **Provider-enforced output.** Anthropic native JSON Schema formuoja atsakymą; aplikacija nebeparsina Markdown fences ranka. Grounding vis tiek lieka programinis post-run downgrade, nes schema neužtikrina citatos teisingumo.

## Security invariants

- System prompt ir `<untrusted_job_posting>` ribos išlaikytos.
- Kandidato profilis, snippet ir tool tekstas aiškiai laikomi duomenimis, ne instrukcijomis.
- Modeliui eksponuojamas tik `get_full_job_description`; filesystem, skill, subagent ir kiti builtin tools išjungti.
- Provider tool schema turi `additionalProperties=false`. Runtime Empty Pydantic modelis papildomus laukus vis tiek ignoruoja gynybiškai. Handler negali naudoti modelio URL.
- Tik sėkmingas tool tekstas pridedamas į `seen_text`; fabricated ar tuščias evidence vis dar nužemina balą iki 3.
- Galutinis dict vis dar validuojamas prieš `schemas/rank_result.schema.json`; visos klaidos grąžina stabilų `_error_result`.

## Test evidence

`tests/scripted_model.py` implementuoja ThinHarness `Model`/`ModelSession` protokolų scripted fake, bet nekopijuoja Harness state machine. `tests/test_ranker.py` per realų Harness tikrina:

- native structured output ir tikslią saugią config;
- tool success/failure ir failure matomumą modeliui be tool retry;
- malicious model URL ignoravimą end-to-end;
- model/tool capacity;
- malformed, empty ir schema-invalid output retry bei safe exhaustion;
- score clamp, permissive legacy list coercion ir grounding downgrade;
- provider request retry tame pačiame pokalbyje, non-retryable 4xx ir apytikslę failed-run statistiką;
- vieno request'o/no-tools preflight su 12 tokenų atsakymo kvota;
- retry po tool call be pakartotinio puslapio gavimo, saugų construction/contract fallback ir operatoriaus logus;
- realų ThinHarness Anthropic provider kelią su HTTP transient ir 4xx atsakymais.

Gryni grounding/coercion ir formalios JSON Schema kontrakto testai lieka atskiri. Galutiniai lokalaus patikrinimo komandų rezultatai turi būti pateikiami pakeitimo acceptance ataskaitoje; šis dokumentas nefiksuoja greitai pasenstančių pass count.

## Live eval limits

Repo `eval/run_eval.py --mock` patikrina tik dataset → scorer → metrics → report grandinę; raktažodžių heuristika nematuoja LLM kokybės. Migracijos aplinkoje realus `ANTHROPIC_API_KEY` nebuvo naudojamas automatiškai. Prieš produkcinį rollout rekomenduojama su įgaliojimais paleisti tą patį dataset prieš/po migracijos ir palyginti label accuracy, score pasiskirstymą, tool naudojimą, grounding downgrade bei token/billing duomenis. Native structured output gali pakeisti modelio formavimo elgesį net kai prompto saugumo ir domeno taisyklės nepasikeitė.
