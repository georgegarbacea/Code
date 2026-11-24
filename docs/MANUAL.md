# LumiBeat Studio – manual de instalare și calibrare

Manualul acoperă instalația ta: 12 profile verticale de 140 cm, câte 6 de fiecare parte a șemineului, bandă COB WS2811 la 12 V, controler BanlanX SP801E (WiFi, Art-Net) cu 4 porturi și 3 profile pe port, cablate în serpentină ↑ ↓ ↑.

---

## 1. Instalare

1. Descarcă `LumiBeat-Studio-Setup-1.0.0.exe` (din GitHub → *Actions* → ultimul build reușit → artefactul **LumiBeat-Studio-Windows**, sau din *Releases*).
2. Rulează instalatorul. Opțiuni disponibile:
   - **Pictogramă pe desktop**
   - **Pornire odată cu Windows** (aplicația pornește minimizată în tray)
   - **Regulă de firewall pentru rețeaua privată**. Lasă opțiunea bifată: fără ea, telefonul nu se poate conecta și răspunsurile ArtPoll de la controler nu ajung la aplicație.
3. Dacă nu vrei să instalezi nimic, folosește varianta portabilă: un singur `LumiBeat Studio.exe`. Prima pornire durează câteva secunde, pentru că se dezarhivează.

Setările, presetările și fotografia peretelui sunt salvate în `%APPDATA%\LumiBeat Studio\`.

> Windows SmartScreen poate afișa „Windows a protejat computerul”, pentru că executabilul nu este semnat cu un certificat comercial. Alege **Mai multe informații → Rulează oricum**.

---

## 2. Pregătirea controlerului SP801E (aplicația BanlanX)

Configurarea internă a SP801E se face doar din aplicația oficială BanlanX, pe telefon:

1. Conectează controlerul la rețeaua WiFi a casei (**mod STA**). În router, rezervă-i o adresă IP fixă (de exemplu `192.168.1.50`).
2. Activează **modul Art-Net**. În modul „Regular” controlerul ignoră Art-Net.
3. Setează tipul de IC: **WS2811**. Ordinea culorilor o poți lăsa RGB, pentru că se corectează și din LumiBeat.
4. Pentru fiecare port setează **numărul de pixeli** (3 profile × pixeli reali pe profil) și **universul de start**.
   Configurația implicită din LumiBeat este *alocare contiguă*: 2 universuri pe port (P1 = U0, P2 = U2, P3 = U4, P4 = U6). Dacă aplicația BanlanX folosește alte universuri, modifică-le în LumiBeat (vezi pasul 4.4) sau apasă **Aplică maparea din controler** după descoperire.
5. Nu mai lăsa aplicația BanlanX să controleze luminile în același timp cu LumiBeat.

---

## 3. Prima pornire

- Aplicația pornește în **modul simulator**: vezi peretele randat live, fără să trimită nimic către LED-uri.
- Sursa audio implicită este **sunetul sistemului (WASAPI Loopback)**. Pornește muzica în Spotify, YouTube, VLC sau în browser și indicatorul *Audio* din antet începe să se miște.
- Fără muzică poți testa totul cu **Setări → Sursă → Piesă demo internă**: un track house de 124 BPM, cu build-up, drop-uri și o pauză de liniște.
- Pentru microfon sau o intrare externă: **Setări → Microfon / intrare externă**, apoi alege dispozitivul.

---

## 4. Calibrare (pagina *Instalație*)

Testele de calibrare ocolesc efectele și adresează direct **pixelii reali**. Pornește transmisia (**Rețea → Trimite cadre către instalație**) ca să vezi testele pe perete.

### 4.1 Porturile
Test **„Porturi”**. Profilele 1–3 trebuie să fie **roșii** (portul 1), 4–6 **verzi**, 7–9 **albastre**, iar 10–12 **albe**.
Dacă un grup are altă culoare, cablul de DATA e pe alt port. Corectează **Port SP801E** la profilele respective.

### 4.2 Direcția DATA
Test **„Direcție DATA”**. Pe **toate** profilele roșul trebuie să fie **jos**, albastrul sus, iar punctul alb trebuie să **urce**.
Dacă un profil arată invers, schimbă-i **Direcție DATA** (↑ = DATA intră jos, ↓ = DATA intră sus). Configurația implicită (↑ ↓ ↑ pe fiecare port) corespunde cablării tale. După acest pas, toate efectele ascendente pornesc fizic de jos.

### 4.3 Numărul real de pixeli
**Atenție: 720 LED-uri pe metru NU înseamnă 720 de pixeli pe metru.** Pe banda COB WS2811 la 12 V, un singur IC WS2811 controlează un segment întreg de LED-uri. Numărul de pixeli adresabili trebuie aflat prin măsurare:

1. Selectează profilul 1 (click pe el în simulator sau în tabel).
2. Alege testul **„Numărare pixeli”** și crește **N** cu ◀ ▶ sau cu sliderul.
3. Când lumina ajunge **exact** la capătul profilului (ultimul pixel aprins e roșu), apasă **Setează pixeli = N**.
4. Repetă pentru fiecare profil, sau folosește **Aplică numărul de pixeli la toate profilele** dacă sunt identice.

Testul **„Marcaje la fiecare 10 pixeli”** te ajută să numeri repede, iar **„Pixel individual”** (cu *Parcurgere automată*) verifică fiecare pixel pe rând.
Dacă la începutul unui segment există pixeli care nu se văd (de exemplu o bucată de bandă ascunsă în colț), setează **Pixeli ignorați la început**.

### 4.4 Universuri
În secțiunea **Porturi & universuri** vezi pentru fiecare port universul de start, canalul de start, câți pixeli intră într-un univers (170 RGB) și ordinea culorilor.
Un port care are nevoie de mai mult de 170 de pixeli continuă automat pe universurile următoare. Raportul de dedesubt semnalează suprapunerile și depășirea capacității (1024 pixeli/port, 4096 în total).

### 4.5 Culori și luminozitate
- **Ordine RGB**: dacă la testul „Culoare solidă → R” se aprinde verde sau albastru, schimbă ordinea portului (de obicei GRB sau BRG).
- **Balans R/G/B** pe profil: egalează albul între profile.
- **Luminozitate maximă globală** și **Limită putere** (implicit 240 W, dintr-o sursă de 500 W). Limitatorul estimează puterea fiecărui cadru (15 W/m la alb complet) și reduce automat luminozitatea, iar puterea estimată apare live în antet.

### 4.6 Fotografia peretelui
**Încarcă fotografie…**, apoi **Poziționează profilele pe foto**. Trage capetele (bulinele) fiecărui profil peste profilul real din fotografie. Ține **Shift** ca profilul să rămână vertical. Simulatorul va randa lumina peste fotografia ta.

---

## 5. Rețea și verificarea compatibilității (pagina *Rețea*)

1. **Caută controlere în rețea** trimite un ArtPoll. Dacă SP801E răspunde, apare în listă cu IP-ul, porturile și universurile lui. Selectează-l, apoi alege **Folosește IP-ul selectat** și, opțional, **Aplică maparea universurilor din controler**.
   Unele firmware-uri nu răspund la ArtPoll. În cazul ăsta introdu IP-ul manual: transmisia unicast funcționează oricum.
2. **Verifică compatibilitatea controlerului** rulează verificările: aceeași subrețea, răspuns ArtPoll, porturi, universuri, capacitate pe port, rata de cadre recomandată pentru WS2811 și WiFi.
3. Activează **Trimite cadre către instalație**.
   - Rata se limitează automat la refresh-ul WS2811 al celui mai lung lanț (252 px ≈ 125 FPS teoretic) și la ținta setată (implicit 40 FPS, potrivită pentru WiFi). La congestie scade singură.
   - Dacă WiFi-ul cade, aplicația se reconectează automat.
   - Oprirea transmisiei sau închiderea aplicației trimite mai întâi un **blackout**, ca LED-urile să nu rămână „înghețate”.

---

## 6. Moduri de utilizare

| Mod | Ce face |
|---|---|
| **Music** | 41 de efecte (din care 8 create special pentru peretele tău), palete, parametri per efect, tranziții |
| **Party** | Spectacol automat: BPM, bătăi, bass drop, build-up/breakdown, schimbă efectele pe frazele muzicale, sincronizează simetric stânga/dreapta, trece în standby ambiental când muzica se oprește. Presetări: Club, Festival, Techno, Disco, House, Chill, Elegant, Auto DJ |
| **Ambient** | Fireplace, Warm White, Golden Hour, Northern Lights, Ocean, Forest, Sunset, Relax, Cinema, Night Mode, Culoare fixă, cu intensitate și temperatură de culoare (1800–6500 K) |
| **Studio** | Editor de efecte din până la 4 straturi: efect, culori, viteză, direcție, simetrie, intensitate, sensibilitate audio, mod de amestec, tranziție. Se salvează ca presetări și se exportă sau importă în format `.json` |

**Stroboscopul** este dezactivat implicit și la fiecare pornire. Se activează doar din bara de jos, după un avertisment despre epilepsia fotosensibilă.
Cât timp e dezactivat, un limitator anti-flash împiedică mai mult de 3 flash-uri pe secundă.

**Mod scenă**: butonul ⛶ (sau F11) afișează simulatorul pe tot ecranul. Ieși cu Esc.

---

## 7. Control de pe telefon

1. Pagina **Telefon**: serverul pornește automat pe portul 8787.
2. Scanează **codul QR** cu telefonul, conectat la același WiFi. Codul QR conține și PIN-ul, deci conectarea e automată. Altfel, deschide adresa afișată și introdu PIN-ul.
3. De pe telefon poți: porni/opri LED-urile, alege Music/Party/Ambient, schimba efectele și paletele, porni Auto DJ, regla luminozitatea, intensitatea și temperatura, alege o culoare, activa stroboscopul (tot cu avertisment) și vedea instalația live.

Securitate: serverul acceptă doar adrese din rețele private, cere PIN și semnează sesiunea. **Nu redirecționa portul în router.** Un PIN nou (buton *Generează PIN nou*) deconectează toate telefoanele.

---

## 8. Pornire automată

**Setări → Pornește automat odată cu Windows**, sau opțiunea echivalentă din instalator. Aplicația pornește minimizată în zona de notificare și continuă ultimul mod folosit. Meniul iconiței din tray are scurtături pentru LED on/off, Party · Auto DJ, Ambient · Fireplace și Ieșire.

---

## 9. Depanare

| Problemă | Soluție |
|---|---|
| Indicatorul audio nu se mișcă | Verifică dacă muzica rulează pe dispozitivul de redare **implicit** din Windows sau alege dispozitivul din *Setări*. Dacă schimbi căștile sau boxele, captura se reconectează singură în ~3 s. |
| BPM instabil | Normal în primele 4–8 secunde ale unei piese și la muzică fără ritm clar. Party trece atunci pe schimbări bazate pe timp. |
| LED-urile nu reacționează | *Rețea → Verifică compatibilitatea*. Cauze frecvente: IP greșit, controlerul nu e în mod Art-Net, PC-ul și controlerul sunt în rețele diferite, firewall. |
| Doar primii 170 de pixeli ai unui port se aprind | Universul al doilea al portului nu corespunde. Compară universurile din aplicația BanlanX cu cele din *Porturi & universuri*. |
| Culori greșite | Schimbă **Ordine RGB** pentru portul respectiv. |
| Un profil e „cu capul în jos” | Schimbă **Direcție DATA** pentru acel profil. |
| Pâlpâiri sau sacadări | Coboară FPS-ul țintă (30–40), activează *Rată adaptivă*, apropie routerul de controler. |
| Simulatorul e negru | *Setări → Rată simulator 30 FPS*. Dacă OpenGL nu e disponibil, aplicația trece automat pe randare software. |

---

## 10. Note electrice pentru instalația ta

- 16,8 m × 15 W/m ≈ **252 W**, adică ≈ **21 A la 12 V** la alb complet. Sursa de 500 W are rezervă. Limitatorul software (implicit 240 W) protejează suplimentar.
- Alimentează fiecare grup de profile separat, cu siguranță pe fiecare ramură. Păstrează **masa comună** între sursă, profile și SP801E. Fără masă comună, semnalul DATA e instabil (pixeli aleatori, pâlpâiri).
- Lanțul de DATA pe port are 4,2 m. Dacă apar erori la capătul lanțului, o rezistență de 33–100 Ω în serie pe DATA, montată la controler, ajută.
