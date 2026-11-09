import csv, random
from pathlib import Path
random.seed(2027)
# city, country, lon, lat, side, parties, name pool   (A = Marek's side, B = Paulo's side)
C = [
 ("Porto","Portugal",-8.61,41.15,"B",7,"pt"), ("Lisbon","Portugal",-9.14,38.72,"B",9,"pt"),
 ("Munich","Germany",11.58,48.14,"A",3,"de"), ("Munich","Germany",11.58,48.14,"B",3,"de"),
 ("Berlin","Germany",13.40,52.52,"A",2,"de"),
 ("Prague","Czechia",14.42,50.08,"A",7,"cz"), ("Karlovy Vary","Czechia",12.87,50.23,"A",5,"cz"),
 ("Plzeň","Czechia",13.38,49.75,"A",2,"cz"), ("Brno","Czechia",16.61,49.20,"A",2,"cz"),
 ("Tokyo","Japan",139.69,35.69,"A",1,"jp"), ("Nicosia","Cyprus",33.38,35.17,"B",1,"cy"),
 ("Mexico City","Mexico",-99.13,19.43,"B",1,"mx"), ("Istanbul","Turkey",28.98,41.01,"A",1,"tr"),
]
FIXED = {"Istanbul": 2}   # exactly two people from Turkey
N = {
 "cz": (["Jana","Tomáš","Petra","Jakub","Lucie","Martin","Kateřina","Ondřej","Tereza","Lukáš","Veronika","Filip","Eva","David","Barbora","Michal"],["Nováková","Dvořák","Černá","Procházka","Kučerová","Veselý","Horáková","Němec","Marková","Pokorný","Králová","Beneš"]),
 "de": (["Anna","Lukas","Sophie","Jonas","Lena","Felix","Marie","Paul","Laura","Maximilian"],["Müller","Schmidt","Weber","Wagner","Becker","Hoffmann","Schäfer","Koch"]),
 "pt": (["Ana","João","Mariana","Pedro","Inês","Tiago","Beatriz","Rui","Catarina","Miguel","Sofia","Diogo","Leonor","Nuno","Rita","André"],["Silva","Santos","Ferreira","Pereira","Oliveira","Costa","Rodrigues","Martins","Sousa","Fernandes","Gonçalves","Lopes"]),
 "jp": (["Yuki","Haruto","Sakura"],["Tanaka","Sato","Suzuki"]), "cy": (["Eleni","Andreas"],["Georgiou","Christodoulou"]),
 "mx": (["Sofía","Diego","Valeria"],["Hernández","García","López"]), "tr": (["Elif","Emre"],["Yılmaz","Demir"]),
}
REL = {"A":["Family","School friends","University (geomatics)","Arcdata colleagues","Friends from Augsburg"],
       "B":["Family","Cousins","Med school friends","Hospital colleagues","Childhood friends"]}
NOTES = {"A":["Bringing a GPS, just in case.","First time in Portugal!","Will dance. Can't be stopped.","Already practising 'obrigado'.","",""],
         "B":["Bringing Avó's famous cake.","Will cry during the vows.","Driving down with the whole family.","Promised to learn one Czech word.","",""]}
SPECIAL = {"Tokyo":"Flying 11 000 km for this!","Mexico City":"Bringing the tequila.","Nicosia":"Sun guaranteed – we're used to it.","Istanbul":"Two of us, one suitcase of baklava."}
rows = []; i = 0
for city,country,lon,lat,side,n,pool in C:
    for _ in range(n):
        i += 1
        fn, ln = random.choice(N[pool][0]), random.choice(N[pool][1])
        if country == "Portugal": mode = random.choice(["Car","Car","Train"])
        else: mode = "Plane" if random.random() < .85 or country not in ("Germany","Czechia") else "Car"
        size = FIXED.get(city) or random.choice([1,2,2,2,3,4])
        rows.append(dict(rsvp_id=f"R{i:03d}", party_lead=f"{fn} {ln}", party_size=size, side=side, relation=random.choice(REL[side]),
            city=city, country=country, lon=lon, lat=lat, transport=mode, arrival_day=random.choice(["Thu","Fri","Fri","Sat"]),
            note=SPECIAL.get(city) if _ == 0 and city in SPECIAL else random.choice(NOTES[side])))
OUT = Path(__file__).resolve().parents[1] / "public/data/rsvps.csv"
with open(OUT,"w",newline="",encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
print(len(rows),"parties,",sum(r["party_size"] for r in rows),"guests")
