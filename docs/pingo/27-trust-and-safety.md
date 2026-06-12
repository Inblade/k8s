# 27 · TRUST & SAFETY
### Blokowanie · Zgłoszenia · Moderacja · Bezpieczny Ping
**Faza 0 (must-have) — bez tego nie wejdziemy do App Store / Google Play**

> Pingo to sieć społecznościowa z geolokalizacją i nastolatkami (16+). Bezpieczeństwo
> nie jest „funkcją Fazy 2" — jest warunkiem publikacji. Ten ekran domyka lukę: w
> specyfikacji v3 nie było ani blokowania, ani zgłoszeń, ani moderacji.

---

## Dlaczego Faza 0

- **Wymóg sklepów.** Apple Guideline 1.2 i Google UGC policy wymagają: zgłaszania
  treści, blokowania użytkowników, filtrowania obraźliwych treści i kontaktu z
  obsługą — *przed* publikacją, inaczej odrzucenie.
- **Geo + małoletni = profil ryzyka.** Lokalizacja na żywo + proximity podnosi
  stawkę nękania i stalkingu. Patrz też `28-minor-safety.md`.
- **Zaufanie = retencja.** Jeden zły incydent bez narzędzi obrony = utrata paczki,
  nie jednego usera.

---

## Ekrany

### 1 · Zgłoś / Zablokuj (action sheet)
Wywoływany z `···` na każdej powierzchni z treścią użytkownika: karta check-inu,
szczegół check-inu, profil, story, wydarzenie, komentarz/reakcja, plan, lista.

```
9:41
‹  Tomek

   Zablokuj Tomka
   nie zobaczy Cię, nie napisze, znika z map i feedu

   Zgłoś Tomka
   nadużycie, nękanie, podszywanie się…

   Ukryj check-iny Tomka
   zostajecie znajomymi, mniej widzisz

   Anuluj
```

- **Blokada jest symetryczna i natychmiastowa.** Po blokadzie: znika z feedu, map,
  list reakcji, RSVP, sugestii i wyszukiwania — obustronnie. Pin znika z mapy.
  Wspólne wydarzenia: oboje widzą event, nie widzą siebie nawzajem.
- **Ukrycie ≠ blokada.** „Ukryj check-iny" to miękka opcja (mniej tarcia niż
  zerwanie znajomości) — odpowiednik mute.

### 2 · Formularz zgłoszenia
```
9:41
‹  Zgłoś

   C O   J E S T   N I E   T A K ?
   ◦ Nękanie lub groźby
   ◦ Niechciany kontakt / śledzenie
   ◦ Treści seksualne
   ◦ Podszywanie się pod kogoś
   ◦ Spam lub oszustwo
   ◦ Fałszywy check-in / lokalizacja
   ◦ Niebezpieczeństwo dla małoletniego        ← priorytet, patrz §Eskalacja
   ◦ Coś innego

   Opisz (opcjonalnie)                      0 / 500

   ☐ Zablokuj też tę osobę   (domyślnie wł.)

   Wyślij zgłoszenie
   Zgłoszenia są anonimowe. Sprawdzamy w ≤ 24 h.
```

- **Snapshot dowodu.** Zgłoszenie zamraża kopię zgłoszonej treści (tekst, media-ref,
  geo, timestamp) w momencie wysłania — żeby usunięcie przez sprawcę nie skasowało
  dowodu. Retencja dowodu: 90 dni (lub do zamknięcia sprawy + 30 dni).
- **Anonimowość.** Zgłaszany nigdy nie widzi, kto zgłosił.
- **Auto-blokada domyślnie włączona** dla kategorii nękanie / niechciany kontakt /
  treści seksualne / zagrożenie małoletniego.

### 3 · Po zgłoszeniu (potwierdzenie + Pingo voice)
```
9:41
        (Pingo — stan: spokojny, troskliwy)

   Mamy to. Zajmiemy się.
   Sprawdzimy w ciągu 24 h. Tomek jest
   zablokowany — nie zobaczy Cię.

   Centrum bezpieczeństwa
   Cofnij blokadę
```

- Ton ciepły, nie biurokratyczny — ale **bez obietnic o karze** (nie informujemy
  zgłaszającego, jaką decyzję podjęliśmy wobec sprawcy, poza faktem „sprawdziliśmy").

---

## Centrum bezpieczeństwa (Ustawienia → Bezpieczeństwo)
Nowa sekcja w `20-ustawienia`:

```
   Zablokowani (3)                →     lista + odblokuj
   Twoje zgłoszenia               →     status: w toku / zamknięte
   Ukryte osoby                   →     mute list
   Słowa, których nie chcę widzieć →    filtr słów w komentarzach (Faza 1)
   Jak działa bezpieczeństwo      →     polityka, prostym językiem
   Kontakt z zespołem             →     formularz pilny / e-mail
```

---

## Moderacja mediów (check-iny, stories, okładki, awatary)

| Warstwa | Mechanizm | Faza |
|---|---|---|
| Upload | Hash-match przeciw znanemu CSAM (PhotoDNA / CSAI Match) **na każdym media** | **0** |
| Upload | Klasyfikator NSFW (nagość/przemoc) → flag do kolejki, nie auto-publikacja przy wysokim score | **0** |
| Tekst | Filtr gróźb/nienawiści w podpisach i komentarzach (lista + ML) | 1 |
| Reaktywnie | Kolejka zgłoszeń ludzi (poniżej) | **0** |

> **CSAM-scanning był w v1 deku, zniknął z v3 — wraca tutaj jako wymóg Fazy 0.**
> Hash-match jest tani i obowiązkowy prawnie; nie mylić z klasyfikatorem NSFW.

---

## Kolejka moderacji (panel zespołu, nie w aplikacji)

- **SLA:** zwykłe zgłoszenie ≤ 24 h; kategoria „zagrożenie małoletniego" lub
  CSAM-hit ≤ 1 h, 24/7 on-call.
- **Priorytetyzacja:** score = waga kategorii × liczba unikalnych zgłoszeń × trust
  score zgłaszających × (czy dotyczy konta 16–17).
- **Akcje moderatora:** usuń treść · ostrzeżenie · zawieszenie 24 h/7 dni · ban ·
  shadow-limit (ukryj z „W pobliżu"/sugestii) · eskalacja prawna.
- **Audyt:** każda akcja logowana (kto, kiedy, dlaczego) — wymóg RODO i odwołań.

### Eskalacja prawna (CSAM / zagrożenie dziecka)
1. Auto-zamrożenie konta sprawcy + zachowanie dowodów (read-only, szyfrowane).
2. Zgłoszenie do **NCMEC / odpowiednika UE** oraz, gdy wymaga prawo, do organów PL.
3. Powiadomienie founder/legal on-call. **€500 legal review z deku — tu się zwraca.**
4. Brak „miękkiego" rozwiązania dla tej kategorii — zero tolerancji.

---

## Bezpieczny Ping & anti-stalking
*(domyka ryzyko proximity z `04`/`07`/`21` — „Pingo widzi, że Kasia jest 350 m od Ciebie")*

- **Ping tylko między znajomymi.** Nieznajomy nie może pingnąć. Zablokowany — nigdy.
- **Rate-limit:** maks. **5 pingów / osobę / dzień** i **20 / dzień łącznie**. Po
  odrzuceniu (brak odpowiedzi 2×) — auto-cooldown 24 h do tej osoby.
- **Proximity-push respektuje kręgi i precyzję:**
  - „X jest 350 m od Ciebie" wysyłamy **tylko** gdy *obie* strony to *Bliscy*
    **i** obie mają precyzję ≥ „ogólna". Nigdy dla kręgu „Znajomi".
  - **Dla kont 16–17 proximity-push jest OFF domyślnie** (patrz `28`).
- **Brak ciągłego trackingu.** Ping/proximity liczone tylko z check-inów (event-based),
  nigdy z tła — zgodnie z obietnicą permissions.
- **Jedno tapnięcie do ucieczki:** każdy push z lokalizacją ma akcję „Tryb ducha"
  i „Zablokuj".

---

## Powierzchnie z wejściem „Zgłoś/Zablokuj"
Profil · check-in (karta + szczegół) · komentarz · reakcja (long-press) · story ·
wydarzenie · plan · lista · wynik wyszukiwania · zaproszenie do znajomych · pin na mapie.
**Reguła:** jeśli widać treść innego użytkownika — widać `···` z akcją bezpieczeństwa.

---

## Stan pusty / krawędzie
- Zablokowanie ostatniego znajomego → wraca empty state z `22-stany` (zaproś paczkę).
- Zgłoszenie własnej treści → niemożliwe (brak `···` na sobie; zamiast tego „Usuń").
- Masowe zgłoszenia z jednego konta (brigading) → trust score zgłaszającego spada,
  waga maleje; ochrona przed report-bombingiem.

---

## Prywatność / RODO
- Dowody i logi moderacji: podstawa prawna = prawnie uzasadniony interes +
  obowiązek prawny (CSAM). Minimalizacja: tylko zgłoszona treść, nie całe konto.
- Zgłaszający i zgłaszany mają prawo do informacji o przetwarzaniu; tożsamość
  zgłaszającego chroniona.
- Zablokowani nie znikają z bazy partnera natychmiast (potrzebne do egzekwowania
  blokady) — usuwane wraz z kontem.

---

## Metryki
- % zgłoszeń obsłużonych w SLA (cel: ≥ 95 % w 24 h; 100 % dla P0 w 1 h).
- Mediana czasu do akcji.
- Recydywa po ostrzeżeniu.
- Block-rate / 1k DAU (zdrowie społeczności; nagły skok = problem).
- Fałszywie-pozytywne NSFW (jakość klasyfikatora).

---

## Zależności techniczne (do stacku z deku)
- Hash-match CSAM: PhotoDNA / CSAI Match (przed zapisem do R2).
- NSFW: model na uploadzie (np. AWS Rekognition / open-source na GPU Hetzner).
- Kolejka: tabela `reports` w Postgres + prosty panel (Go + chi).
- Audyt: append-only log.
- On-call: Sentry alert → PagerDuty/Telegram dla P0.
```
