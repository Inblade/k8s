# 28 · OCHRONA MAŁOLETNICH (16–17)
### Bezpieczne domyślne · Bramki kontaktu · Weryfikacja wieku
**Faza 0 (must-have) — strefa najwyższej odpowiedzialności produktu**

> W speku v3 fraza „Konta 16–17: dodatkowe zabezpieczenia" pojawia się dwa razy,
> ale nie ma ani jednego ekranu ani reguły. Ten dokument zamienia deklarację w
> konkretny spec. Pingo jest 16+, więc **każdy nowy user może być małoletni** —
> projektujemy najpierw dla nich, dorosłym luzujemy.

---

## Zasada nadrzędna
**Privacy-by-default jest *ściślejsze* dla 16–17 i nie da się go „rozluźnić" poniżej
progu bezpieczeństwa.** Nastolatek może zacieśnić, nie może otworzyć się na ryzyko
jednym tapnięciem.

---

## Jak rozpoznajemy konto małoletnie
- Wiek z **bramki wieku 16+** (kołowrotek roczników, ekran `02`).
- Flaga `is_minor` = `true` dla `16 ≤ wiek < 18`, liczona z daty, nie deklaracji ad-hoc.
- **Próg przesuwa się sam:** w dniu 18. urodzin konto dostaje **opt-in** ofertę
  poluzowania ustawień — nic nie zmienia się automatycznie bez zgody.
- Wiek = pole wrażliwe; nie pokazujemy go publicznie, nie da się go „podbić" bez
  ponownej weryfikacji (anti-tamper).

---

## Bezpieczne domyślne dla 16–17 (różnice vs. dorosły)

| Funkcja | Dorosły (domyślnie) | 16–17 (domyślnie, twardo) |
|---|---|---|
| Widoczność check-inów | Znajomi | **Bliscy** |
| Precyzja lokalizacji | Dokładna dla Bliskich | **Ogólna (nazwa miejsca), bez pinu** |
| „W pobliżu" / Hot miejsca | Wł. | **Wył.** (brak wystawiania nieznajomym) |
| Proximity-push („X 350 m") | Wł. dla Bliskich | **Wył.** |
| Pojawianie się w wyszukiwarce | Po @handle i sugestiach | **Tylko po dokładnym @handle** (nie w sugestiach obcych) |
| Kto może wysłać zaproszenie | Znajomi znajomych | **Tylko wspólni znajomi / z linku** |
| Kto może pingnąć | Znajomi | Znajomi (bez zmian) |
| Web-RSVP widzi profil | Imię + idący | **Tylko imię, bez @handle i historii** |
| Zostań twórcą (`16`) | Dostępne | **Niedostępne < 18** (wideo-selfie małoletniego = nie) |
| Marketing push | Wył. (i tak) | **Wył. i zablokowane do zmiany** |

> Ekran ustawień małoletniego pokazuje te pola jako **„chronione"** (ikona tarczy),
> z krótkim wyjaśnieniem zamiast zwykłego toggle'a tam, gdzie nie wolno otworzyć.

---

## Ekrany

### 1 · Bramka wieku — wariant 16–17 (rozszerza `02`)
Po wyborze rocznika dającego 16–17:
```
9:41
   Masz 16 lat — super, że jesteś.

   Twoje konto startuje w trybie bezpiecznym:
   ◦ widzą Cię tylko Bliscy
   ◦ pokazujemy dzielnicę, nie dokładny pin
   ◦ nie wyświetlamy Cię obcym w pobliżu

   Możesz to zmienić, gdy skończysz 18 lat.

   Rozumiem, zaczynamy
   Co to znaczy „tryb bezpieczny"?
```

### 2 · Ustawienia chronione (wariant `19`/`20` dla 16–17)
```
9:41
‹  Prywatność

   🛡  Tryb bezpieczny (16–17)        aktywny

   Kto widzi check-iny
   Bliscy            ✓ (max otwartości: Znajomi)
   — nie możesz ustawić „Wszyscy/publiczne"

   Precyzja lokalizacji
   Ogólna  ·  Szeroka  ·  Ukryta
   — „Dokładna" niedostępna w trybie bezpiecznym

   Wystawianie obcym                 zablokowane 🛡
   W pobliżu, Hot miejsca, proximity — wyłączone

   Wszystko możesz zacieśnić. Poluzować — po 18.
```

### 3 · Bariera kontaktu dorosły → małoletni
Gdy konto 18+ próbuje zaprosić / pingnąć / komentować profil 16–17 **bez wspólnego
znajomego ani wspólnego, zaakceptowanego eventu**:
```
9:41
        (Pingo — stan: spokojny, stanowczy)

   Najpierw wspólni znajomi
   To konto jest chronione. Możesz dodać tę osobę,
   gdy macie wspólnego znajomego albo wspólne
   wydarzenie, na które oboje idziecie.

   Rozumiem
```
- Sygnał jest **cichy dla małoletniego** (nie straszymy „dorosły Cię szukał"),
  ale interakcja nie dochodzi do skutku.
- Wzorzec „adult-minor contact gating" znany z Instagrama/TikToka — graf zamiast
  otwartego DM/ping.

---

## Reguły kontaktu (macierz)

| Inicjator → Cel | 16–17 cel | 18+ cel |
|---|---|---|
| 16–17 inicjator | OK (jak zwykle) | OK |
| 18+ inicjator, **brak** wspólnego grafu | **Zablokowane** (ekran 3) | OK |
| 18+ inicjator, **jest** wspólny znajomy / wspólny event | OK | OK |
| Ktokolwiek zablokowany | Nigdy | Nigdy |

„Inicjacja" = zaproszenie do znajomych, ping, komentarz/reakcja do nieznajomego,
wiadomość przez story-reply.

---

## Weryfikacja wieku — pragmatycznie
Bramka self-declared (jak teraz) jest tania, ale obchodzilna. Warstwujemy ryzyko,
nie budujemy hard-KYC dla 16-latka (to samo w sobie problem prywatności):

- **Faza 0:** self-declared + anti-tamper (nie da się zmienić wieku bez supportu) +
  **age-inference jako sygnał ryzyka** (np. deklarowany 16 vs. sygnały konta) →
  flaguje do moderacji, nie blokuje automatycznie.
- **Faza 1:** przy podejrzanej zmianie/odwołaniu — opcjonalna miękka estymacja
  wieku (np. Yoti/age-estimation na selfie, **wynik zero-retencji**, tylko bucket
  wiekowy, zgodne z RODO). Nigdy nie wymagamy dokumentu od nastolatka domyślnie.
- **Twórcy:** wymóg 18+ realnie egzekwowany na etapie wideo-selfie (`16`).

---

## RODO / prawo (kontekst PL + UE)
- **Zgoda i wiek:** w PL wiek zgody na usługi społeczeństwa informacyjnego = 16 lat
  (art. 8 RODO, implementacja PL) — dlatego próg 16+, nie wymóg zgody rodzica.
  Poniżej 16 — konto niedozwolone.
- **DSA (art. 28):** zakaz profilowania reklamowego małoletnich + obowiązek
  „wysokiego poziomu prywatności/bezpieczeństwa" w domyślnych ustawieniach — nasze
  defaulty to realizują wprost.
- **Minimalizacja danych:** nie zbieramy lokalizacji w tle dla nikogo; dla
  małoletnich dodatkowo nie wystawiamy precyzyjnej geo.
- **Wideo-selfie weryfikacji:** dla małoletnich nie zbieramy (twórcy 18+); ogólnie
  retencja 24 h, potem usunięcie — bez wyjątków.

---

## Powiązania
- Twarde defaulty zasilają kręgi i precyzję z `19-prywatnosc`.
- Bramki kontaktu współdzielą block/report z `27-trust-and-safety`.
- CSAM-scanning (`27`) jest tu szczególnie krytyczny.

---

## Metryki / red-flags
- % kont 16–17, które próbują „otworzyć" ustawienia (czy default jest zbyt ciasny?).
- Liczba zablokowanych prób kontaktu 18+→małoletni (zdrowie bariery).
- Zgłoszenia kategorii „zagrożenie małoletniego" — bezwzględny priorytet, trend.
- Konta z podejrzaną zmianą wieku → kolejka moderacji.
```
