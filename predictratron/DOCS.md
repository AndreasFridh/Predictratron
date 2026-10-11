# Predictratron — användning och data

Första fungerande versionen av en generell, lokal ML-app för Home Assistant.
Skapa separata modellinstanser med egna inputs, mål, upplösning och prognoslängd.
Exempel: temperatur → timförbrukning eller nederbörd + vecka → markvattennivå.
ML-boxen väljer tidsperiod för både träning och prediktion: minut, timme, dygn,
vecka eller ett eget fast intervall på 1–525 600 minuter.

## Starta

Med Docker Desktop eller Docker Engine och Compose:

```sh
docker compose up -d --build
```

Öppna [appen](http://localhost:8080). Den fungerar med CSV och de inbyggda
demomodellerna även utan en HA-anslutning. Modeller, historik och träningsresultat
sparas i datavolymen `predictor-data`.

## Installera som Home Assistant-app

Lägg till `https://github.com/AndreasFridh/Predictratron` som repository i
Home Assistants appbutik. Installera **Predictratron**, starta appen och välj
**Öppna webbgränssnitt**. Home Assistant OS eller Supervisor krävs.

## Anslut Home Assistant

Vid installation genom appbutiken används appens egen Supervisor-inloggning
automatiskt. Du behöver ingen egen token. Följande gäller separat Docker-drift.

Kopiera `.env.example` till `.env` och ange din HA-adress och befintliga
API-inloggning. `HA_URL` är rotadressen utan `/api`.
Hemligheter läses på servern och lämnas inte ut i appens API eller gränssnitt.

```dotenv
HA_URL=http://homeassistant.local:8123
HA_TOKEN=din_befintliga_api_token
APP_TOKEN=egen_nyckel_for_den_har_appen
```

Starta om tjänsten med `docker compose up -d --force-recreate`.
Alternativt kan en hemlig fil monteras i containern och anges med
`HA_TOKEN_FILE=/run/secrets/ha_token`.
`HA_CA_FILE` kan peka på en monterad CA-fil vid egen certifikatutfärdare.
HTTPS-certifikat verifieras; använd en adress som matchar certifikatet.

Compose exponerar appen på **localhost**. Vid LAN-åtkomst ändrar du
portbindningen till din serveradress och sätter `APP_TOKEN`.
Webbläsaren frågar då efter appens nyckel. HA-nyckeln ska aldrig anges där.

Appen kan nu installeras genom Home Assistants appbutik. Se repots README för
installationslänken. Docker Compose är alternativet för en separat Docker-värd.

## Arbetsflöde

1. Välj **Ny modell** för en egen arbetsyta med en ML-box.
2. Dra inputsignaler, kalenderfält och en output från **Signaler** till arbetsytan.
3. Öppna signalens kugghjul och ange namn, datatyp och HA-sensor eller CSV-kolumn.
4. Dra från inputsignalens cirkel till ML-boxens ingång, och från ML till output.
5. Ange datakälla, tidsperiod, prognoslängd och historikfönster i **ML-inställningar**.
   Tidsperioden kan också öppnas direkt med periodknappen i ML-boxen.
6. Välj **Spara modell**. Kopplingarna avgör vilka signaler som används.
7. Hämta HA-historik eller importera CSV via **Resultat**.
8. Välj **1. Träna på historik** i ML-boxen. Det skapar och utvärderar instansens tränade modell.
9. Välj **2. Prediktera framtid** för att använda den tränade modellen på senaste historiken.
   Resultat visar framtida värden, testfel och jämförelseprognos. Prediktion tränar inte om modellen.
10. Publicera manuellt i HA om du vill ha en prognossensor där.

Varje ML-box har en egen modellinstans med identitet, sensorval, historik,
träningsfil, kvalitetstest och prognos. Instanser delar inte tränade vikter eller
historik. I denna version har varje instans en egen arbetsyta med en ML-box.
Boxen visar mängden historik och har separata knappar för träning och prediktion.
CSV kan importeras direkt från arbetsytan; HA-instansen har **Hämta historik**.
Prediktionsknappen kräver en tränad modell och båda stegen låses medan instansen arbetar.
Träningsjobb körs ett i taget för att begränsa
resursanvändningen. Använd **Spara som ny modell** för att prova ett separat flöde.
Noder kan flyttas och kopplingar tas bort genom att klicka på linjen. Klick på
utgång och sedan ingång fungerar också. Positioner och kopplingar sparas per modell.
En ändring av modellens inputs eller prognosinställningar kräver ny träning;
flytt och namnbyte behåller träningen. Befintlig historik behålls när en input
kopplas bort. Byte av datakälla, period eller målsignal efter import kräver en
ny modell för att undvika att olika mätserier blandas. Radering av hela
modellinstanser är inte implementerat.

Signaler visas som **○ – Namn (Datatyp)**. Float är decimaltal, Integer är
heltal och Boolean är 0/1. Output kan vara Float eller Integer; modellen gör
numerisk regression. Vecka och andra kalenderfält skapas automatiskt.

**Automatisk uppdatering** hämtar historik och uppdaterar appens prognos var
15:e minut när appen körs. Den tränar om efter det valda antalet dagar.
Publicering till HA är i denna version ett separat, manuellt steg.

## Vad betyder ett mätvärde?

Alla tidsstämplar i appens lagring och API är i UTC och anger **slutet på
en avslutad mätperiod**. En rad märkt `2026-10-11T10:00:00Z` beskriver alltså
timmen 09:00–10:00 UTC. En prognospunkt innehåller både `start` och `end`.

Timmodeller arbetar med 60 minuter. Dygnsmodeller arbetar med 24 timmar mellan
UTC-midnätter. Veckomodeller arbetar med sju dygn, måndag 00:00 till nästa måndag
00:00 UTC. Egna fasta intervall anges i minuter; veckomultiplar förankras i
måndag och övriga intervall i Unix-epoken. De är inte lokala kalenderdygn på
23/25 timmar vid sommartidsbyte. Kalendermånader och kalenderår stöds inte ännu.
Kalenderfält beräknas i modellens valda tidszon, normalt Europe/Stockholm.

**Veckosnitt:** välj en vecka i ML-boxen och medelvärde på outputsignalen.
Fyra framtida perioder ger fyra separata framtida veckosnitt. Summor och senaste
värde kan väljas per signal, exempelvis veckosumma för nederbörd och veckosnitt
för vattennivå. Alla inputs sammanställs till samma period som output.
Fördröjningar och historikfönster räknas i dessa valda perioder, alltså veckor
för en veckomodell. Inställningsdialogen visar period och total prognoslängd.
Grova perioder kräver lång historik: minst 100 användbara prognosstarter behövs
även för veckomodeller. Veckovalet föreslår tre års historik.

För HA-signaler väljer du:

| Typ | Användning |
| --- | --- |
| Medelvärde | Temperatur, markfukt, vattennivå och andra mätvärden |
| Senaste värde | Mätningen vid periodens slut; kräver tillgänglig state/raw-historik |
| Mätarökning | Energi eller nederbörd från en ackumulerande mätare med HA:s förändringsstatistik |

HA:s långtidsstatistik hämtas via WebSocket och resetjusterad `change` används
för mätarökning. Därmed räknas en kumulativ energimätare inte som periodförbrukning.
Om medelvärdes- eller senaste-värde-statistik saknas hämtas tillgänglig råhistorik
via REST. Råa medelvärden vägs efter hur länge varje tillstånd gällt, inte bara
antal uppdateringar. `on`/`off` blir 1/0. Okänd eller otillgänglig historik blir
saknade värden, inte noll. Råhistoriken kan vara mycket kortare än långtidsstatistiken.

Dygnsvärden byggs från 24 kompletta timvärden, veckor från 168. Ofullständiga
perioder markeras som saknade. För intervall som inte är multiplar av en timme
används HA:s femminutersstatistik om periodlängden är delbar med fem minuter;
andra intervall använder tillgänglig råhistorik för medelvärde/senaste värde.
Mätarökning kräver perioder delbara med fem minuter. Korttidsstatistik och
råhistorik kan finnas för betydligt kortare tid än långtidsstatistik.
En sensor med effekt i W behöver först omvandlas till energi om målet
är kWh per timme. Appen gör ingen automatisk enhetskonvertering.

## Exempel: markvattennivå

- Mål: faktisk uppmätt vattennivå i cm, eller markfukt i % om det är det du mäter.
- Input: nederbörd från en ackumulerande regnmätare.
- Kalender: vecka och årstid.
- Upplösning: ett dygn.
- Prognos: sju dygn.
- Fördröjningar: `0, 1, 2, 7, 14` dygn.
- Historikfönster: `3, 7, 14` dygn; både summa och medelvärde räknas fram.
- Tidigare målvärden: på.

Modellen får därmed information om markens senaste nivå och regnet under flera
föregående dygn. Grundvattennivå och markfukt är olika mätningar; välj den verkliga
målsensorn och dess enhet. Det behövs observerade målvärden för att träna.
Som jämförelse kan du skapa en kopia med tidigare målvärden avstängda och se om
nederbörd och kalender ensamma tillför tillräcklig information.

Den inbyggda markvattendemonstrationen använder **syntetiska** mätvärden.
Den bevisar arbetsflödet, inte hydrologisk precision.

## CSV-format

CSV ska innehålla värden för avslutade perioder, med samma nycklar som modellens
mål och inputs. Välj **CSV-radernas tidsperiod** före import. Standard är samma
period som ML-boxen; tim- eller dygnsrader kan också sammanställas till veckor.
Källperioden måste vara en jämn del av modellperioden. Uppsampling stöds inte.
Vid sammanställning används signalens medelvärde, summa, mätarökning (summa av
redan angivna periodökningar) eller senaste värde. Hela perioden måste finnas.
CSV räknar inte differenser från kumulativa mätarställningar.
`timestamp` måste ha tidszon, till exempel `Z` eller `+02:00`, och efter omräkning
till UTC ligga på gränsen för vald källperiod. Veckor har måndagsgränser i UTC.
Tomma celler är tillåtna; texter, oändliga värden, framtida tider och dubbla
tidsstämplar nekas. Integer kräver heltal och Boolean kräver 0 eller 1.
Import av samma tidsstämpel uppdaterar filens signalvärden; tidigare värden för
signaler som tillfälligt kopplats bort behålls.

```csv
timestamp,water_level,rain
2026-01-02T00:00:00Z,42.1,3.2
2026-01-03T00:00:00Z,43.0,0.0
```

Här är `rain` nederbörd i respektive avslutat dygn, inte regnmätarens totalsiffra.
Det behövs minst 100 användbara prognosstarter efter historikfönster, luckor och
prognoslängd, samt tillräcklig historik för att skilja träning från test.

## Modell och utvärdering

Första versionen använder en Random Forest med flera framtida målvärden.
Den predikterar varje framtida period direkt; egna prognoser matas inte tillbaka
som om de vore uppmätta värden. Fördröjningar och rullande fönster använder enbart
data fram till prognosstart. Kalenderfält använder cyklisk kodning.

De sista cirka 20 procenten av användbara prognosstarter används som historiktest.
Träningsstarter vars framtida målvärden överlappar testperioden tas bort.
Saknade inputs kan ersättas med träningsperiodens median; målvärden ersätts aldrig
för att skapa träningsetiketter. Senaste målvärdet och senaste inputs måste finnas
för en ny prognos. Detaljerad utvärdering per prognosavstånd finns i API-resultatet.

MAE är genomsnittligt absolut fel i målets enhet. Modellen jämförs med två enkla
alternativ: senaste uppmätta värdet och samma tid förra veckan. Det bästa alternativet
visas som jämförelse. En modell som inte slår det märks tydligt i gränssnittet.
Diagrammet för historiktestet visar en period framåt; sammanfattat MAE omfattar
hela den valda prognoslängden. Trädmodellens input-vikter är inga orsakssamband.

Efter utvärderingen tränas den slutliga modellen om på all användbar historik.
Prognosbandet använder 90:e percentilen av absoluta testfel per prognosavstånd.
Det är en beskrivning av historisk felstorlek, inte ett separat kalibrerat
konfidensintervall eller en garanti om framtida täckning.

## Nuvarande gränser

- Numeriska mål och inputs; binära HA-tillstånd stöds som 0/1. Kategorier och fria
  texter behöver omvandlas innan de används.
- Inputs är **observerad historik**. Framtida nederbörd, temperatur eller planerade
  tillstånd tas inte in ännu. Modellen kan alltså inte veta att det ska regna i morgon.
- Nästa utbyggnad bör spara väderprognoser med både utfärdandetid och giltighetstid.
  Då kan framtida väder användas och testas utan att verkligt framtida väder råkar
  ge ett orealistiskt bra historiktest.
- Historikluckor interpoleras inte. Långa eller omfattande luckor kan ge för lite
  träningsdata. All lagring sker lokalt; automatisk gallring finns inte ännu.
- Färsk historik krävs. Vid eftersläpning kortas prognosen så att redan avslutade
  prognosperioder inte skickas ut. Prognoser äldre än två mätperioder nekas via API.
- Trädmodeller har begränsad förmåga att extrapolera långt utanför träningsvärdena.
- HA-anslutningens faktiska sensorhistorik och precision ska valideras på din installation.

## Output till Home Assistant

Knappen **Publicera i HA** skapar eller uppdaterar `sensor.ml_<modell-id>` via
HA:s REST-API. Tillståndet är värdet för nästa framtida prognosperiod.
Attributen innehåller period, utfärdandetid och hela prognosserien.
Demodata kan inte publiceras som verkliga HA-prognoser.

En state som skapas så här är inte en registrerad integration och försvinner vid
HA-omstart tills den publiceras igen. För kontinuerlig användning kan HA:s
RESTful-sensor läsa `/api/models/<id>/forecast`, eller en riktig integration/MQTT
discovery läggas till i nästa version. Prognossensorn ska inte behandlas som en
mätare för faktisk energi i Energy Dashboard.

## API

API:t finns under `/api`. När `APP_TOKEN` är satt behövs
`Authorization: Bearer <appens nyckel>`.

| Metod | Sökväg | Funktion |
| --- | --- | --- |
| GET | `/status` | Konfigurationsstatus utan hemligheter |
| GET | `/entities` | Valbara HA-sensorer |
| GET / POST | `/models` | Lista eller skapa modellinstanser |
| POST | `/graphs` | Skapa modell från noder och kopplingar |
| PUT | `/models/<id>/graph` | Spara arbetsyta och härledda modellinställningar |
| GET | `/models/<id>` | Inställningar, datamängd, status, testresultat och prognos |
| GET | `/models/<id>/history` | Senaste 200 målvärdena |
| POST | `/models/<id>/csv` | CSV-import; multipartfält `file`, valfritt `interval_minutes` för källperioden |
| POST | `/models/<id>/actions/sync` | Hämta HA-historik |
| POST | `/models/<id>/actions/train` | Träna och utvärdera |
| POST | `/models/<id>/actions/forecast` | Gör prognos |
| POST | `/models/<id>/actions/run` | Hämta HA-historik, träna och gör prognos |
| POST | `/models/<id>/actions/publish` | Gör aktuell prognos och publicera i HA |
| GET | `/models/<id>/forecast` | Läs aktuell prognos |
| POST | `/demo/energy` eller `/demo/water` | Skapa syntetisk demomodell |

Jobb körs i bakgrunden. Följ modellens `status` och `error` via GET.
`/health` finns utanför API-autentiseringen för containerkontrollen.

## Flera separata containrar

Samma container kan innehålla många modellinstanser. För full isolering kan du
köra fler containrar med olika portar och datavolymer, exempelvis:

```sh
docker run -d --name predictor-water -p 127.0.0.1:8081:8080 \
  -v predictor-water-data:/data predictratron:0.2.0
```

Dela inte samma datavolym mellan flera processer eller containrar.

## Utveckling och kontroller

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8080
```

Källor för anslutningsmetoder och tidsserieutvärdering:
[HA REST API](https://developers.home-assistant.io/docs/api/rest/),
[HA WebSocket API](https://developers.home-assistant.io/docs/api/websocket/),
[HA statistik](https://data.home-assistant.io/docs/statistics/),
[scikit-learn: fördröjda tidsseriefält](https://scikit-learn.org/stable/auto_examples/applications/plot_time_series_lagged_features.html).
