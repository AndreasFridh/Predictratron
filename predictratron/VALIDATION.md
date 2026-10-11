# Verifiering — 11 oktober 2026

- 56 automatiska tester passerade.
- Docker-imagen byggdes och startades på Docker Desktop med Linux/ARM64.
- Predictratron 0.2.0 byggdes som HA-app med Supervisor-metadata för aarch64.
  Den startade med tom datavolym och körde tjänsten med uid 10001.
- Ingress-sökvägar, relativa resurser, begränsning till Supervisor-klienten,
  falska vidarebefordrade IP-adresser och HA:s separata WebSocket-proxy testades.
- Gränssnittet och modellskapande kördes genom en lokal webbproxy med
  `/api/hassio_ingress/.../` som bas. Statiska resurser och API-anrop fungerade.
- Supervisor-uppstart använder appens egen serviceinloggning; ingen befintlig
  token från en annan app kopierades. Ett separat GitHub-repo har installerbar
  appstruktur, dokumentation, ändringslogg och automatiska kontroller.
- Containerns hälsokontroll passerade.
- Två separata demomodeller tränades och skapade prognoser genom containerns API.
- Elförbrukningsdemonstrationen producerade 24 timvärden.
- Markvattendemonstrationen producerade sju dygnsvärden.
- Historiktestets sista träningsmål ligger före den första teststarten.
- Separata modeller behåller egen historik och egna träningsfiler.
- Lagring över omstart verifierades i API-tester; containerns datavolym består
  också vid återskapande av containern.
- CSV-validering, åtkomstnyckel, tidszoner, saknade värden, råhistorikens tidsvägning
  och komplett dygnsaggregering kontrollerades.
- JavaScriptets syntax kontrollerades och gränssnittet granskades i appens webbläsare.
- Dragning av signal från paletten, flytt av nod, dragkoppling mellan portar,
  alternativ klickkoppling, borttagning av koppling och sparning verifierades i webbläsaren.
- Sparade positioner och kopplingar återställdes efter omladdning. ML-inställningar
  öppnades och sparades, och befintlig modell kunde göra en ny prognos.
- Grafvalidering, datatyper, kompatibilitet med äldre träningsfiler och bevarad
  historik vid bortkoppling/återkoppling kontrollerades i automatiska tester.
- Separat träning och prediktion verifierades: träning skapar ingen prognos,
  prediktion tränar inte om och en andra instans förblir helt oförändrad.
- ML-boxens egna knappar användes i webbläsaren för träning och prediktion.
  Elinstansen tränades på sin egen historik. Markvatteninstansen gav en prognos;
  elinstansens äldre historik nekades korrekt av färskhetskontrollen.
- Minut-, tim-, dygns-, vecko- och egna fasta periodgränser kontrollerades.
- Tim-/dygns-CSV sammanställdes till kompletta veckor med medelvärde, summa
  och senaste värde. Luckor, felaktiga gränser och uppsampling nekades.
- Veckomodellen tränades och producerade fyra framtida veckovärden i testerna.
  HA-timstatistik till veckor, femminutersstatistik till 15 minuter och råhistorikens
  tidsvägning över veckor verifierades med testdata.
- I webbläsaren verifierades eget 15-minutersintervall med åtta perioder = två
  timmar samt veckointervall med fyra perioder = fyra veckor. En tom separat
  CSV-instans, Markvattennivå · veckosnitt, sparades för import av riktig historik.

De syntetiska exemplens utvärdering vid denna körning:

| Exempel | Modellens MAE | Bästa jämförelsens MAE | Resultat |
| --- | --- | --- | --- |
| Elförbrukning | 0,152 kWh | 0,204 kWh | Lägre modellfel |
| Markvattennivå | 4,153 cm | 4,043 cm | Modellen slog inte jämförelsen; varning visas |

Detta är påhittade data och siffrorna är inte ett mått på faktisk precision i
användarens installation. Demodata beror även på datumet då de skapas.

**Inte verifierat:** autentiserad anslutning från den här containern till
användarens Home Assistant, verklig sensorhistorik, publicering i den verkliga
HA-installationen, verklig prognosprecision eller andra processorarkitekturer lokalt.
Ingen Home Assistant-konfiguration eller enhet ändrades i denna uppgift.

Testmiljön gav en deprecationsvarning från testklienten om dess httpx-adapter;
alla tester passerade och varningen gäller testverktyget.
