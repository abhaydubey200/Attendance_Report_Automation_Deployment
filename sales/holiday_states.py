"""Each Field Sales person's holiday state (which page of HR's holiday list applies to them).

The staff list has no state, so the app SUGGESTS one from where the person usually marks attendance (their most frequent
GPS start point over the last months) and the nearest known town; HR confirms it (one click for all sure suggestions) or
picks another state. Only a confirmed state is used for holidays. A suggestion is "sure" only when the start point is
within SURE_KM of a known town AND the nearest town that would give a DIFFERENT holiday list is at least MARGIN_KM further
away - people near a border, far from any known town or without GPS are left for HR to choose.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

SURE_KM, MARGIN_KM, LOOKBACK_DAYS = 60.0, 30.0, 120

# (town, state, lat, lng) - state capitals, large cities and district towns where the field team works
PLACES = [
    # Delhi / NCR
    ("New Delhi", "Delhi", 28.61, 77.21), ("Gurugram", "Haryana", 28.46, 77.03), ("Faridabad", "Haryana", 28.41, 77.32),
    ("Noida", "Uttar Pradesh", 28.54, 77.39), ("Ghaziabad", "Uttar Pradesh", 28.67, 77.45), ("Sonipat", "Haryana", 28.99, 77.02),
    ("Panipat", "Haryana", 29.39, 76.97), ("Karnal", "Haryana", 29.69, 76.99), ("Rohtak", "Haryana", 28.90, 76.61),
    ("Hisar", "Haryana", 29.15, 75.72), ("Ambala", "Haryana", 30.38, 76.78), ("Rewari", "Haryana", 28.20, 76.62),
    ("Yamunanagar", "Haryana", 30.13, 77.27), ("Sirsa", "Haryana", 29.53, 75.03), ("Bhiwani", "Haryana", 28.79, 76.13),
    # Punjab / Chandigarh / HP / J&K
    ("Chandigarh", "Chandigarh", 30.73, 76.78), ("Ludhiana", "Punjab", 30.90, 75.85), ("Amritsar", "Punjab", 31.63, 74.87),
    ("Jalandhar", "Punjab", 31.33, 75.58), ("Patiala", "Punjab", 30.34, 76.39), ("Bathinda", "Punjab", 30.21, 74.95),
    ("Mohali", "Punjab", 30.70, 76.72), ("Pathankot", "Punjab", 32.27, 75.65), ("Hoshiarpur", "Punjab", 31.53, 75.91),
    ("Firozpur", "Punjab", 30.92, 74.61), ("Shimla", "Himachal Pradesh", 31.10, 77.17), ("Solan", "Himachal Pradesh", 30.90, 77.10),
    ("Baddi", "Himachal Pradesh", 30.96, 76.79), ("Mandi", "Himachal Pradesh", 31.71, 76.93), ("Dharamshala", "Himachal Pradesh", 32.22, 76.32),
    ("Una", "Himachal Pradesh", 31.47, 76.27), ("Jammu", "Jammu and Kashmir", 32.73, 74.86), ("Srinagar", "Jammu and Kashmir", 34.08, 74.80),
    ("Kathua", "Jammu and Kashmir", 32.37, 75.52), ("Anantnag", "Jammu and Kashmir", 33.73, 75.15),
    # Uttarakhand
    ("Dehradun", "Uttarakhand", 30.32, 78.03), ("Haridwar", "Uttarakhand", 29.95, 78.16), ("Roorkee", "Uttarakhand", 29.87, 77.89),
    ("Haldwani", "Uttarakhand", 29.22, 79.51), ("Rudrapur", "Uttarakhand", 28.98, 79.40), ("Kashipur", "Uttarakhand", 29.21, 78.96),
    ("Rishikesh", "Uttarakhand", 30.09, 78.27), ("Almora", "Uttarakhand", 29.60, 79.66),
    # Uttar Pradesh
    ("Lucknow", "Uttar Pradesh", 26.85, 80.95), ("Kanpur", "Uttar Pradesh", 26.45, 80.33), ("Agra", "Uttar Pradesh", 27.18, 78.01),
    ("Varanasi", "Uttar Pradesh", 25.32, 82.97), ("Prayagraj", "Uttar Pradesh", 25.44, 81.85), ("Meerut", "Uttar Pradesh", 28.98, 77.71),
    ("Bareilly", "Uttar Pradesh", 28.37, 79.43), ("Moradabad", "Uttar Pradesh", 28.84, 78.77), ("Aligarh", "Uttar Pradesh", 27.88, 78.08),
    ("Gorakhpur", "Uttar Pradesh", 26.76, 83.37), ("Saharanpur", "Uttar Pradesh", 29.96, 77.55), ("Muzaffarnagar", "Uttar Pradesh", 29.47, 77.70),
    ("Mathura", "Uttar Pradesh", 27.49, 77.67), ("Jhansi", "Uttar Pradesh", 25.45, 78.57), ("Ayodhya", "Uttar Pradesh", 26.79, 82.20),
    ("Sultanpur", "Uttar Pradesh", 26.26, 82.07), ("Azamgarh", "Uttar Pradesh", 26.07, 83.18), ("Jaunpur", "Uttar Pradesh", 25.75, 82.69),
    ("Mirzapur", "Uttar Pradesh", 25.15, 82.57), ("Ghazipur", "Uttar Pradesh", 25.58, 83.58), ("Ballia", "Uttar Pradesh", 25.76, 84.15),
    ("Basti", "Uttar Pradesh", 26.80, 82.73), ("Deoria", "Uttar Pradesh", 26.50, 83.78), ("Gonda", "Uttar Pradesh", 27.13, 81.96),
    ("Bahraich", "Uttar Pradesh", 27.57, 81.60), ("Sitapur", "Uttar Pradesh", 27.57, 80.68), ("Lakhimpur", "Uttar Pradesh", 27.95, 80.78),
    ("Shahjahanpur", "Uttar Pradesh", 27.88, 79.91), ("Hardoi", "Uttar Pradesh", 27.40, 80.13), ("Etawah", "Uttar Pradesh", 26.78, 79.02),
    ("Firozabad", "Uttar Pradesh", 27.15, 78.40), ("Rae Bareli", "Uttar Pradesh", 26.23, 81.23), ("Banda", "Uttar Pradesh", 25.48, 80.33),
    ("Fatehpur", "Uttar Pradesh", 25.93, 80.81), ("Pratapgarh", "Uttar Pradesh", 25.90, 81.95), ("Bulandshahr", "Uttar Pradesh", 28.40, 77.85),
    ("Rampur", "Uttar Pradesh", 28.81, 79.03), ("Pilibhit", "Uttar Pradesh", 28.63, 79.80), ("Barabanki", "Uttar Pradesh", 26.93, 81.19),
    ("Unnao", "Uttar Pradesh", 26.55, 80.49), ("Mainpuri", "Uttar Pradesh", 27.23, 79.02), ("Farrukhabad", "Uttar Pradesh", 27.39, 79.58),
    # Madhya Pradesh / Chhattisgarh
    ("Bhopal", "Madhya Pradesh", 23.26, 77.41), ("Indore", "Madhya Pradesh", 22.72, 75.86), ("Jabalpur", "Madhya Pradesh", 23.18, 79.95),
    ("Gwalior", "Madhya Pradesh", 26.22, 78.18), ("Ujjain", "Madhya Pradesh", 23.18, 75.78), ("Sagar", "Madhya Pradesh", 23.84, 78.74),
    ("Rewa", "Madhya Pradesh", 24.53, 81.30), ("Satna", "Madhya Pradesh", 24.58, 80.83), ("Ratlam", "Madhya Pradesh", 23.33, 75.04),
    ("Dewas", "Madhya Pradesh", 22.97, 76.05), ("Khandwa", "Madhya Pradesh", 21.82, 76.35), ("Chhindwara", "Madhya Pradesh", 22.06, 78.94),
    ("Vidisha", "Madhya Pradesh", 23.53, 77.81), ("Katni", "Madhya Pradesh", 23.83, 80.39), ("Shivpuri", "Madhya Pradesh", 25.42, 77.66),
    ("Raipur", "Chhattisgarh", 21.25, 81.63), ("Bilaspur", "Chhattisgarh", 22.08, 82.15), ("Durg", "Chhattisgarh", 21.19, 81.28),
    ("Korba", "Chhattisgarh", 22.36, 82.75), ("Raigarh", "Chhattisgarh", 21.90, 83.40), ("Jagdalpur", "Chhattisgarh", 19.08, 82.02),
    ("Ambikapur", "Chhattisgarh", 23.12, 83.20),
    # Rajasthan / Gujarat
    ("Jaipur", "Rajasthan", 26.91, 75.79), ("Jodhpur", "Rajasthan", 26.24, 73.02), ("Udaipur", "Rajasthan", 24.59, 73.71),
    ("Kota", "Rajasthan", 25.18, 75.83), ("Ajmer", "Rajasthan", 26.45, 74.64), ("Bikaner", "Rajasthan", 28.02, 73.31),
    ("Alwar", "Rajasthan", 27.55, 76.60), ("Bhilwara", "Rajasthan", 25.35, 74.63), ("Sikar", "Rajasthan", 27.61, 75.14),
    ("Sri Ganganagar", "Rajasthan", 29.91, 73.88), ("Bharatpur", "Rajasthan", 27.22, 77.49), ("Jhunjhunu", "Rajasthan", 28.13, 75.40),
    ("Pali", "Rajasthan", 25.77, 73.32), ("Tonk", "Rajasthan", 26.17, 75.79), ("Bhiwadi", "Rajasthan", 28.21, 76.86),
    ("Ahmedabad", "Gujarat", 23.02, 72.57), ("Surat", "Gujarat", 21.17, 72.83), ("Vadodara", "Gujarat", 22.31, 73.18),
    ("Rajkot", "Gujarat", 22.30, 70.80), ("Gandhinagar", "Gujarat", 23.22, 72.65), ("Bhavnagar", "Gujarat", 21.76, 72.15),
    ("Jamnagar", "Gujarat", 22.47, 70.06), ("Anand", "Gujarat", 22.56, 72.95), ("Nadiad", "Gujarat", 22.69, 72.86),
    ("Mehsana", "Gujarat", 23.60, 72.37), ("Bharuch", "Gujarat", 21.71, 72.98), ("Vapi", "Gujarat", 20.37, 72.90),
    ("Navsari", "Gujarat", 20.95, 72.95), ("Palanpur", "Gujarat", 24.17, 72.43), ("Junagadh", "Gujarat", 21.52, 70.46),
    ("Godhra", "Gujarat", 22.78, 73.61), ("Himmatnagar", "Gujarat", 23.60, 72.97),
    # Maharashtra / Goa
    ("Mumbai", "Maharashtra", 19.08, 72.88), ("Thane", "Maharashtra", 19.22, 72.98), ("Navi Mumbai", "Maharashtra", 19.03, 73.03),
    ("Kalyan", "Maharashtra", 19.24, 73.13), ("Vasai", "Maharashtra", 19.39, 72.84), ("Palghar", "Maharashtra", 19.70, 72.77),
    ("Pune", "Maharashtra", 18.52, 73.86), ("Nashik", "Maharashtra", 20.00, 73.79), ("Nagpur", "Maharashtra", 21.15, 79.09),
    ("Aurangabad", "Maharashtra", 19.88, 75.34), ("Solapur", "Maharashtra", 17.66, 75.91), ("Kolhapur", "Maharashtra", 16.70, 74.24),
    ("Sangli", "Maharashtra", 16.85, 74.58), ("Satara", "Maharashtra", 17.69, 74.00), ("Ahmednagar", "Maharashtra", 19.09, 74.74),
    ("Jalgaon", "Maharashtra", 21.00, 75.56), ("Dhule", "Maharashtra", 20.90, 74.77), ("Amravati", "Maharashtra", 20.93, 77.75),
    ("Akola", "Maharashtra", 20.70, 77.00), ("Latur", "Maharashtra", 18.40, 76.57), ("Nanded", "Maharashtra", 19.15, 77.31),
    ("Chandrapur", "Maharashtra", 19.96, 79.30), ("Ratnagiri", "Maharashtra", 16.99, 73.30), ("Alibag", "Maharashtra", 18.64, 72.87),
    ("Baramati", "Maharashtra", 18.15, 74.58), ("Wardha", "Maharashtra", 20.74, 78.60), ("Beed", "Maharashtra", 18.99, 75.76),
    ("Panaji", "Goa", 15.49, 73.83), ("Margao", "Goa", 15.27, 73.96),
    # Karnataka / Telangana / Andhra Pradesh
    ("Bengaluru", "Karnataka", 12.97, 77.59), ("Mysuru", "Karnataka", 12.30, 76.64), ("Hubballi", "Karnataka", 15.36, 75.12),
    ("Mangaluru", "Karnataka", 12.91, 74.86), ("Belagavi", "Karnataka", 15.85, 74.50), ("Kalaburagi", "Karnataka", 17.33, 76.83),
    ("Ballari", "Karnataka", 15.14, 76.92), ("Davanagere", "Karnataka", 14.46, 75.92), ("Shivamogga", "Karnataka", 13.93, 75.57),
    ("Tumakuru", "Karnataka", 13.34, 77.10), ("Vijayapura", "Karnataka", 16.83, 75.71), ("Hassan", "Karnataka", 13.00, 76.10),
    ("Udupi", "Karnataka", 13.34, 74.75), ("Kolar", "Karnataka", 13.14, 78.13), ("Raichur", "Karnataka", 16.20, 77.36),
    ("Bidar", "Karnataka", 17.91, 77.52), ("Chitradurga", "Karnataka", 14.23, 76.40), ("Mandya", "Karnataka", 12.52, 76.90),
    ("Hosapete", "Karnataka", 15.27, 76.39), ("Chikkamagaluru", "Karnataka", 13.32, 75.77), ("Gadag", "Karnataka", 15.43, 75.63),
    ("Hyderabad", "Telangana", 17.39, 78.49), ("Warangal", "Telangana", 17.97, 79.59), ("Karimnagar", "Telangana", 18.44, 79.13),
    ("Nizamabad", "Telangana", 18.67, 78.09), ("Khammam", "Telangana", 17.25, 80.15), ("Mahbubnagar", "Telangana", 16.74, 78.00),
    ("Nalgonda", "Telangana", 17.05, 79.27), ("Adilabad", "Telangana", 19.67, 78.53), ("Siddipet", "Telangana", 18.10, 78.85),
    ("Visakhapatnam", "Andhra Pradesh", 17.69, 83.22), ("Vijayawada", "Andhra Pradesh", 16.51, 80.65), ("Guntur", "Andhra Pradesh", 16.31, 80.44),
    ("Tirupati", "Andhra Pradesh", 13.63, 79.42), ("Nellore", "Andhra Pradesh", 14.44, 79.99), ("Kurnool", "Andhra Pradesh", 15.83, 78.04),
    ("Rajahmundry", "Andhra Pradesh", 17.00, 81.80), ("Kakinada", "Andhra Pradesh", 16.99, 82.25), ("Kadapa", "Andhra Pradesh", 14.47, 78.82),
    ("Anantapur", "Andhra Pradesh", 14.68, 77.60), ("Eluru", "Andhra Pradesh", 16.71, 81.10), ("Ongole", "Andhra Pradesh", 15.50, 80.05),
    ("Srikakulam", "Andhra Pradesh", 18.30, 83.90), ("Vizianagaram", "Andhra Pradesh", 18.11, 83.40), ("Chittoor", "Andhra Pradesh", 13.22, 79.10),
    ("Machilipatnam", "Andhra Pradesh", 16.19, 81.14),
    # Tamil Nadu / Puducherry / Kerala
    ("Chennai", "Tamil Nadu", 13.08, 80.27), ("Coimbatore", "Tamil Nadu", 11.02, 76.96), ("Madurai", "Tamil Nadu", 9.93, 78.12),
    ("Tiruchirappalli", "Tamil Nadu", 10.79, 78.70), ("Salem", "Tamil Nadu", 11.66, 78.15), ("Tirunelveli", "Tamil Nadu", 8.71, 77.76),
    ("Erode", "Tamil Nadu", 11.34, 77.72), ("Vellore", "Tamil Nadu", 12.92, 79.13), ("Thanjavur", "Tamil Nadu", 10.79, 79.14),
    ("Tiruppur", "Tamil Nadu", 11.11, 77.34), ("Hosur", "Tamil Nadu", 12.74, 77.83), ("Kanchipuram", "Tamil Nadu", 12.83, 79.70),
    ("Nagercoil", "Tamil Nadu", 8.18, 77.41), ("Dindigul", "Tamil Nadu", 10.36, 77.98), ("Thoothukudi", "Tamil Nadu", 8.76, 78.13),
    ("Krishnagiri", "Tamil Nadu", 12.52, 78.21), ("Villupuram", "Tamil Nadu", 11.94, 79.49), ("Cuddalore", "Tamil Nadu", 11.75, 79.75),
    ("Karur", "Tamil Nadu", 10.96, 78.08), ("Namakkal", "Tamil Nadu", 11.22, 78.17), ("Tiruvannamalai", "Tamil Nadu", 12.23, 79.07),
    ("Puducherry", "Puducherry", 11.94, 79.81),
    ("Thiruvananthapuram", "Kerala", 8.52, 76.94), ("Kochi", "Kerala", 9.93, 76.27), ("Kozhikode", "Kerala", 11.26, 75.78),
    ("Thrissur", "Kerala", 10.53, 76.21), ("Kollam", "Kerala", 8.89, 76.61), ("Kannur", "Kerala", 11.87, 75.37),
    ("Palakkad", "Kerala", 10.78, 76.65), ("Kottayam", "Kerala", 9.59, 76.52), ("Alappuzha", "Kerala", 9.50, 76.34),
    ("Malappuram", "Kerala", 11.07, 76.07),
    # Odisha / Bihar / Jharkhand / West Bengal / North East
    ("Bhubaneswar", "Odisha", 20.30, 85.82), ("Cuttack", "Odisha", 20.46, 85.88), ("Rourkela", "Odisha", 22.26, 84.85),
    ("Sambalpur", "Odisha", 21.47, 83.97), ("Berhampur", "Odisha", 19.31, 84.79), ("Balasore", "Odisha", 21.49, 86.93),
    ("Puri", "Odisha", 19.81, 85.83), ("Jharsuguda", "Odisha", 21.86, 84.01), ("Angul", "Odisha", 20.84, 85.10),
    ("Patna", "Bihar", 25.59, 85.14), ("Gaya", "Bihar", 24.80, 85.00), ("Muzaffarpur", "Bihar", 26.12, 85.39),
    ("Bhagalpur", "Bihar", 25.24, 86.98), ("Darbhanga", "Bihar", 26.15, 85.90), ("Purnia", "Bihar", 25.78, 87.47),
    ("Begusarai", "Bihar", 25.42, 86.13), ("Arrah", "Bihar", 25.56, 84.66), ("Chhapra", "Bihar", 25.78, 84.73),
    ("Motihari", "Bihar", 26.65, 84.92), ("Sasaram", "Bihar", 24.95, 84.03), ("Siwan", "Bihar", 26.22, 84.36),
    ("Hajipur", "Bihar", 25.69, 85.21), ("Samastipur", "Bihar", 25.86, 85.78), ("Bettiah", "Bihar", 26.80, 84.50),
    ("Saharsa", "Bihar", 25.88, 86.60), ("Munger", "Bihar", 25.38, 86.47), ("Katihar", "Bihar", 25.54, 87.57),
    ("Ranchi", "Jharkhand", 23.34, 85.31), ("Jamshedpur", "Jharkhand", 22.80, 86.20), ("Dhanbad", "Jharkhand", 23.80, 86.43),
    ("Bokaro", "Jharkhand", 23.67, 86.15), ("Hazaribagh", "Jharkhand", 23.99, 85.36), ("Deoghar", "Jharkhand", 24.48, 86.70),
    ("Giridih", "Jharkhand", 24.19, 86.30), ("Dumka", "Jharkhand", 24.27, 87.25), ("Daltonganj", "Jharkhand", 24.04, 84.07),
    ("Kolkata", "West Bengal", 22.57, 88.36), ("Howrah", "West Bengal", 22.59, 88.31), ("Durgapur", "West Bengal", 23.52, 87.31),
    ("Asansol", "West Bengal", 23.67, 86.95), ("Siliguri", "West Bengal", 26.73, 88.40), ("Kharagpur", "West Bengal", 22.35, 87.23),
    ("Bardhaman", "West Bengal", 23.23, 87.86), ("Krishnanagar", "West Bengal", 23.40, 88.50), ("Malda", "West Bengal", 25.01, 88.14),
    ("Berhampore", "West Bengal", 24.10, 88.25), ("Haldia", "West Bengal", 22.03, 88.06), ("Bankura", "West Bengal", 23.23, 87.07),
    ("Cooch Behar", "West Bengal", 26.32, 89.45), ("Jalpaiguri", "West Bengal", 26.52, 88.72), ("Barasat", "West Bengal", 22.72, 88.48),
    ("Guwahati", "Assam", 26.14, 91.74), ("Dibrugarh", "Assam", 27.47, 94.91), ("Silchar", "Assam", 24.83, 92.78),
    ("Jorhat", "Assam", 26.75, 94.20), ("Tezpur", "Assam", 26.63, 92.80), ("Nagaon", "Assam", 26.35, 92.68),
    ("Bongaigaon", "Assam", 26.48, 90.56), ("Dhubri", "Assam", 26.02, 89.98), ("Tinsukia", "Assam", 27.49, 95.36),
    ("Shillong", "Meghalaya", 25.58, 91.89), ("Agartala", "Tripura", 23.83, 91.28), ("Imphal", "Manipur", 24.82, 93.94),
    ("Kohima", "Nagaland", 25.67, 94.11), ("Dimapur", "Nagaland", 25.91, 93.73), ("Aizawl", "Mizoram", 23.73, 92.72),
    ("Itanagar", "Arunachal Pradesh", 27.08, 93.61), ("Gangtok", "Sikkim", 27.33, 88.61),
]


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def _home(points: list[tuple[float, float]]) -> tuple[tuple[float, float], int] | None:
    """The most frequent start area (5 km cells), and how many points are within 15 km of it."""
    if not points:
        return None
    cell = Counter((round(a * 20) / 20, round(b * 20) / 20) for a, b in points).most_common(1)[0][0]
    near = [p for p in points if km(p, cell) <= 15]
    lat, lng = sum(p[0] for p in near) / len(near), sum(p[1] for p in near) / len(near)
    return (round(lat, 4), round(lng, 4)), len(near)


def suggest_for(point: tuple[float, float], region_of) -> dict:
    """Nearest known town -> state; 'sure' only with a clear margin to any town of a different holiday list."""
    ranked = sorted(((km(point, (p[2], p[3])), p) for p in PLACES), key=lambda x: x[0])
    d1, best = ranked[0]
    group = region_of(best[1])
    other = next(((d, p) for d, p in ranked if region_of(p[1]) != group), None)
    sure = d1 <= SURE_KM and (other is None or other[0] - d1 >= MARGIN_KM)
    why = f"usually starts {d1:.0f} km from {best[0]} ({best[1]})"
    if other and not sure:
        why += f"; {other[1][0]} ({other[1][1]}) is {other[0]:.0f} km away"
    return {"state": best[1], "town": best[0], "km": round(d1, 1), "sure": sure, "why": why,
            "other": other[1][1] if other else None}


def suggestions(session: Session, today: date | None = None) -> list[dict]:
    """Every active Field Sales person: current holiday state (if any) and the GPS suggestion."""
    from daily import holiday_list
    from database.models.sales import SalesEmployee, SalesLocation
    today = today or date.today()
    cal = holiday_list.years(session).get(str(today.year), {})

    def region_of(state: str) -> str:
        r = holiday_list.region_for(cal, state)
        return r["name"] if r else f"(no list) {state}"

    pts: dict[str, list] = defaultdict(list)
    for code, lat, lng in session.execute(select(SalesLocation.code, SalesLocation.lat, SalesLocation.lng).where(
            SalesLocation.kind == "ATT", SalesLocation.day >= today - timedelta(days=LOOKBACK_DAYS))):
        pts[code].append((lat, lng))
    out = []
    for e in session.scalars(select(SalesEmployee).where(SalesEmployee.status == "ACTIVE").order_by(SalesEmployee.name)):
        h = _home(pts.get(e.code, []))
        s = suggest_for(h[0], region_of) if h else None
        if s:
            s["points"] = h[1]
        out.append({"code": e.code, "name": e.name, "manager": e.manager_name or "", "hod": e.hod_name or "",
                    "state": e.holiday_state, "state_by": e.holiday_state_by, "suggestion": s,
                    "list": region_of(e.holiday_state) if e.holiday_state else None,
                    "agrees": bool(s and e.holiday_state and region_of(s["state"]) == region_of(e.holiday_state))})
    return out


def set_state(session: Session, code: str, state: str | None, actor: str, how: str = "HR") -> None:
    from daily.holiday_list import STATES
    from database.models.sales import SalesEmployee
    if state is not None and state not in STATES:
        raise ValueError(f"Unknown state '{state}'.")
    e = session.scalar(select(SalesEmployee).where(SalesEmployee.code == code))
    if e is None:
        raise LookupError(f"{code} is not on the Field Sales staff list.")
    e.holiday_state, e.holiday_state_by = state, (f"{how} ({actor})" if state else None)
    session.flush()


def accept_sure(session: Session, actor: str) -> int:
    """HR accepts every SURE suggestion for people who have no state yet."""
    n = 0
    for x in suggestions(session):
        if not x["state"] and x["suggestion"] and x["suggestion"]["sure"]:
            set_state(session, x["code"], x["suggestion"]["state"], actor, "GPS suggestion accepted")
            n += 1
    return n


def person_holidays(session: Session, day: date, staff: list | None = None) -> dict[str, str]:
    """code -> holiday name, for staff whose confirmed state has a holiday on `day` in HR's list."""
    from daily import holiday_list
    from database.models.sales import SalesEmployee
    cal = holiday_list.years(session).get(str(day.year))
    if not cal:
        return {}
    staff = staff if staff is not None else list(session.scalars(select(SalesEmployee)))
    names: dict[str, str | None] = {}
    out = {}
    for e in staff:
        if not e.holiday_state:
            continue
        if e.holiday_state not in names:
            names[e.holiday_state] = holiday_list.holidays_on(session, day, e.holiday_state)
        if names[e.holiday_state]:
            out[e.code] = names[e.holiday_state]
    return out
