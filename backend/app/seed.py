"""Fleet, delivery and depot seed data.

These are simulated operational entities -- a real deployment reads them from
PostgreSQL and live GPS (roadmap Phase 2/4). They are labelled as simulated
everywhere in the UI. The live layers (weather, seismic, road geometry,
routing) are genuinely fetched from the internet.
"""

from __future__ import annotations

from typing import Dict, List

DEPOTS: List[dict] = [
    {"id": "DEP-GHY", "name": "Guwahati Central Depot",  "city": "guwahati", "capacity_pct": 78},
    {"id": "DEP-SCL", "name": "Silchar Transit Hub",     "city": "silchar",  "capacity_pct": 64},
    {"id": "DEP-AJL", "name": "Aizawl Regional Store",   "city": "aizawl",   "capacity_pct": 31},
    {"id": "DEP-IMF", "name": "Imphal Distribution Point","city": "imphal",  "capacity_pct": 45},
    {"id": "DEP-DBR", "name": "Dibrugarh Forward Depot",  "city": "dibrugarh","capacity_pct": 82},
    {"id": "DEP-GTK", "name": "Gangtok Hill Depot",       "city": "gangtok",  "capacity_pct": 27},
]

# corridor_id, progress, direction, cargo, priority, vehicle type
VEHICLES: List[dict] = [
    {"id": "TR-104",      "plate": "MZ-01-TR-104", "corridor_id": "NH306-SCL-AJL", "progress": 0.28,
     "direction": 1, "cargo": "Emergency Medicine", "priority": "critical", "type": "medical",
     "driver": "R. Lalthanzara", "phone": "+91 98561 40112", "payload_t": 4.2, "cold_chain": True},
    {"id": "AS-27-4182",  "plate": "AS-27-C-4182", "corridor_id": "NH27-GHY-DBR", "progress": 0.44,
     "direction": 1, "cargo": "Fuel", "priority": "high", "type": "tanker",
     "driver": "B. Hazarika", "phone": "+91 94351 22087", "payload_t": 18.0, "cold_chain": False},
    {"id": "MN-08-2194",  "plate": "MN-08-B-2194", "corridor_id": "NH29-DMU-IMF", "progress": 0.62,
     "direction": 1, "cargo": "Food Grain", "priority": "standard", "type": "truck",
     "driver": "L. Singh", "phone": "+91 87652 11934", "payload_t": 22.5, "cold_chain": False},
    {"id": "MZ-05-8831",  "plate": "MZ-05-A-8831", "corridor_id": "NH306-AJL-LGL", "progress": 0.36,
     "direction": 1, "cargo": "Vaccines", "priority": "critical", "type": "medical",
     "driver": "C. Hmingthanmawia", "phone": "+91 90876 55210", "payload_t": 1.8, "cold_chain": True},
    {"id": "NL-01-7420",  "plate": "NL-01-K-7420", "corridor_id": "NH39-JRH-DMU", "progress": 0.55,
     "direction": -1, "cargo": "Construction Material", "priority": "standard", "type": "truck",
     "driver": "T. Angami", "phone": "+91 88765 43021", "payload_t": 26.0, "cold_chain": False},
    {"id": "ML-05-3321",  "plate": "ML-05-H-3321", "corridor_id": "NH6-GHY-SCL", "progress": 0.30,
     "direction": 1, "cargo": "Medical Supplies", "priority": "high", "type": "medical",
     "driver": "D. Sangma", "phone": "+91 96157 78432", "payload_t": 6.4, "cold_chain": True},
    {"id": "AS-01-5520",  "plate": "AS-01-G-5520", "corridor_id": "NH27-GHY-SLG", "progress": 0.68,
     "direction": -1, "cargo": "Consumer Goods", "priority": "standard", "type": "truck",
     "driver": "P. Das", "phone": "+91 98640 90125", "payload_t": 19.2, "cold_chain": False},
    {"id": "TR-88-2210",  "plate": "TR-88-D-2210", "corridor_id": "NH8-AGT-SCL", "progress": 0.50,
     "direction": 1, "cargo": "Relief Material", "priority": "high", "type": "truck",
     "driver": "S. Debbarma", "phone": "+91 94021 33078", "payload_t": 14.8, "cold_chain": False},
    {"id": "SK-01-9042",  "plate": "SK-01-J-9042", "corridor_id": "NH10-SLG-GTK", "progress": 0.47,
     "direction": 1, "cargo": "Oxygen Cylinders", "priority": "critical", "type": "medical",
     "driver": "K. Bhutia", "phone": "+91 90325 66471", "payload_t": 8.0, "cold_chain": False},
    {"id": "AR-02-1177",  "plate": "AR-02-F-1177", "corridor_id": "NH13-ITN-TWG", "progress": 0.33,
     "direction": 1, "cargo": "Winter Supplies", "priority": "high", "type": "truck",
     "driver": "N. Tsering", "phone": "+91 89123 44560", "payload_t": 12.0, "cold_chain": False},
    {"id": "AS-15-6603",  "plate": "AS-15-M-6603", "corridor_id": "NH15-TZP-ITN", "progress": 0.21,
     "direction": 1, "cargo": "Cement", "priority": "standard", "type": "truck",
     "driver": "J. Bora", "phone": "+91 97060 12388", "payload_t": 24.0, "cold_chain": False},
    {"id": "MN-04-5512",  "plate": "MN-04-L-5512", "corridor_id": "NH37-SCL-IMF", "progress": 0.58,
     "direction": 1, "cargo": "Blood Units", "priority": "critical", "type": "medical",
     "driver": "H. Meitei", "phone": "+91 91234 87650", "payload_t": 0.9, "cold_chain": True},
]

# vehicle_id -> delivery definition
DELIVERIES: List[dict] = [
    {"id": "DLV-2041", "vehicle_id": "TR-104",     "cargo": "Emergency Medicine",
     "origin": "Guwahati", "destination": "Aizawl",   "priority": "critical", "sla_hours": 8,
     "consignee": "Aizawl Civil Hospital", "units": "420 cartons"},
    {"id": "DLV-2028", "vehicle_id": "AS-27-4182", "cargo": "Fuel",
     "origin": "Guwahati", "destination": "Dibrugarh", "priority": "high", "sla_hours": 14,
     "consignee": "IOC Dibrugarh Terminal", "units": "18 kL"},
    {"id": "DLV-2031", "vehicle_id": "MN-08-2194", "cargo": "Food Grain",
     "origin": "Dimapur", "destination": "Imphal",    "priority": "standard", "sla_hours": 10,
     "consignee": "FCI Imphal", "units": "450 bags"},
    {"id": "DLV-2035", "vehicle_id": "MZ-05-8831", "cargo": "Vaccines",
     "origin": "Aizawl", "destination": "Lunglei",    "priority": "critical", "sla_hours": 6,
     "consignee": "Lunglei District Hospital", "units": "1,200 doses"},
    {"id": "DLV-2022", "vehicle_id": "NL-01-7420", "cargo": "Construction Material",
     "origin": "Jorhat", "destination": "Dimapur",    "priority": "standard", "sla_hours": 12,
     "consignee": "PWD Nagaland", "units": "26 t"},
    {"id": "DLV-2026", "vehicle_id": "ML-05-3321", "cargo": "Medical Supplies",
     "origin": "Guwahati", "destination": "Silchar",   "priority": "high", "sla_hours": 9,
     "consignee": "Silchar Medical College", "units": "180 cartons"},
    {"id": "DLV-2021", "vehicle_id": "AS-01-5520", "cargo": "Consumer Goods",
     "origin": "Siliguri", "destination": "Guwahati",  "priority": "standard", "sla_hours": 16,
     "consignee": "Regional Warehouse", "units": "19 t"},
    {"id": "DLV-2030", "vehicle_id": "TR-88-2210", "cargo": "Relief Material",
     "origin": "Agartala", "destination": "Silchar",   "priority": "high", "sla_hours": 7,
     "consignee": "SDRF Cachar", "units": "14 t"},
    {"id": "DLV-2033", "vehicle_id": "SK-01-9042", "cargo": "Oxygen Cylinders",
     "origin": "Siliguri", "destination": "Gangtok",   "priority": "critical", "sla_hours": 5,
     "consignee": "STNM Hospital Gangtok", "units": "96 cylinders"},
    {"id": "DLV-2038", "vehicle_id": "AR-02-1177", "cargo": "Winter Supplies",
     "origin": "Itanagar", "destination": "Tawang",    "priority": "high", "sla_hours": 18,
     "consignee": "Tawang District Admin", "units": "12 t"},
    {"id": "DLV-2024", "vehicle_id": "AS-15-6603", "cargo": "Cement",
     "origin": "Tezpur", "destination": "Itanagar",    "priority": "standard", "sla_hours": 11,
     "consignee": "NHIDCL Site 4", "units": "24 t"},
    {"id": "DLV-2040", "vehicle_id": "MN-04-5512", "cargo": "Blood Units",
     "origin": "Silchar", "destination": "Imphal",     "priority": "critical", "sla_hours": 6,
     "consignee": "RIMS Imphal Blood Bank", "units": "140 units"},
]

DELIVERY_BY_VEHICLE: Dict[str, dict] = {d["vehicle_id"]: d for d in DELIVERIES}

# Inventory for the logistics-intelligence panel (roadmap Phase 8).
INVENTORY: List[dict] = [
    {"depot_id": "DEP-AJL", "item": "Emergency Medicine", "stock_days": 1.8, "status": "shortage"},
    {"depot_id": "DEP-AJL", "item": "IV Fluids",          "stock_days": 2.4, "status": "shortage"},
    {"depot_id": "DEP-GHY", "item": "Emergency Medicine", "stock_days": 14.0, "status": "surplus"},
    {"depot_id": "DEP-GTK", "item": "Oxygen Cylinders",   "stock_days": 1.2, "status": "shortage"},
    {"depot_id": "DEP-DBR", "item": "Fuel",               "stock_days": 11.5, "status": "surplus"},
    {"depot_id": "DEP-IMF", "item": "Food Grain",         "stock_days": 6.0, "status": "normal"},
    {"depot_id": "DEP-SCL", "item": "Relief Material",    "stock_days": 9.2, "status": "surplus"},
]
