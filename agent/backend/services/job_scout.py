from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.db.jobs_repository import (
    company_source_scanned_recently,
    count_company_active_jobs,
    has_applied_to_title,
    make_job_id,
    record_company_source_scan,
    upsert_job,
    utc_today,
)
from backend.models.job_models import JobRecord
from backend.services.career_discovery import discover_company_targets, normalize_company_name
from backend.services.config import settings
from backend.services.company_catalog import select_company_search_pool
from backend.services.files import load_profile
from backend.services.job_sources import (
    fetch_ashby_jobs,
    fetch_glassdoor_jobs,
    fetch_greenhouse_jobs,
    fetch_icims_jobs,
    fetch_indeed_jobs,
    fetch_jobvite_jobs,
    fetch_lever_jobs,
    fetch_linkedin_jobs,
    fetch_smartrecruiters_jobs,
    fetch_taleo_jobs,
    fetch_workday_jobs,
)
from backend.services.matcher import match_job


WORKDAY_DISCOVERY_MAP = {
    # ── Verified endpoints (expanded Apr 11 2026 — ~120 companies) ──
    # ── Big Tech / Semiconductors / SaaS ────────────────────────────────
    "netflix": {"company": "Netflix", "endpoint": "https://netflix.wd1.myworkdayjobs.com/wday/cxs/netflix/Netflix/jobs"},
    "salesforce": {"company": "Salesforce", "endpoint": "https://salesforce.wd12.myworkdayjobs.com/wday/cxs/salesforce/External_Career_Site/jobs"},
    "adobe": {"company": "Adobe", "endpoint": "https://adobe.wd5.myworkdayjobs.com/wday/cxs/adobe/external_experienced/jobs"},
    "crowdstrike": {"company": "CrowdStrike", "endpoint": "https://crowdstrike.wd5.myworkdayjobs.com/wday/cxs/crowdstrike/crowdstrikecareers/jobs"},
    "palo_alto": {"company": "Palo Alto Networks", "endpoint": "https://paloaltonetworks.wd5.myworkdayjobs.com/wday/cxs/paloaltonetworks/panwexternalcareers/jobs"},
    "nvidia": {"company": "NVIDIA", "endpoint": "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs"},
    "autodesk": {"company": "Autodesk", "endpoint": "https://autodesk.wd1.myworkdayjobs.com/wday/cxs/autodesk/Ext/jobs"},
    "intel": {"company": "Intel", "endpoint": "https://intel.wd1.myworkdayjobs.com/wday/cxs/intel/External/jobs"},
    "broadcom": {"company": "Broadcom", "endpoint": "https://broadcom.wd1.myworkdayjobs.com/wday/cxs/broadcom/External_Career/jobs"},
    "applied_materials": {"company": "Applied Materials", "endpoint": "https://amat.wd1.myworkdayjobs.com/wday/cxs/amat/External/jobs"},
    "motorola_solutions": {"company": "Motorola Solutions", "endpoint": "https://motorolasolutions.wd5.myworkdayjobs.com/wday/cxs/motorolasolutions/Careers/jobs"},
    "workday": {"company": "Workday", "endpoint": "https://workday.wd5.myworkdayjobs.com/wday/cxs/workday/Workday/jobs"},
    "servicetitan": {"company": "ServiceTitan", "endpoint": "https://servicetitan.wd1.myworkdayjobs.com/wday/cxs/servicetitan/ServiceTitan/jobs"},
    "cadence": {"company": "Cadence Design Systems", "endpoint": "https://cadence.wd1.myworkdayjobs.com/wday/cxs/cadence/External_Careers/jobs"},
    "workiva": {"company": "Workiva", "endpoint": "https://workiva.wd1.myworkdayjobs.com/wday/cxs/workiva/careers/jobs"},
    "gen_digital": {"company": "Gen Digital (Norton/Avast)", "endpoint": "https://gen.wd1.myworkdayjobs.com/wday/cxs/gen/careers/jobs"},
    "unisys": {"company": "Unisys", "endpoint": "https://unisys.wd5.myworkdayjobs.com/wday/cxs/unisys/External/jobs"},
    "alteryx": {"company": "Alteryx", "endpoint": "https://alteryx.wd108.myworkdayjobs.com/wday/cxs/alteryx/AlteryxCareers/jobs"},
    "snap": {"company": "Snap Inc.", "endpoint": "https://snapchat.wd1.myworkdayjobs.com/wday/cxs/snapchat/sourced/jobs"},
    "samsung_us": {"company": "Samsung Electronics America", "endpoint": "https://sec.wd3.myworkdayjobs.com/wday/cxs/sec/Samsung_Careers/jobs"},
    "ciena": {"company": "Ciena", "endpoint": "https://ciena.wd5.myworkdayjobs.com/wday/cxs/ciena/Careers/jobs"},
    # ── Payments / Fintech / Banking / Capital Markets ───────────────────
    "mastercard": {"company": "Mastercard", "endpoint": "https://mastercard.wd1.myworkdayjobs.com/wday/cxs/mastercard/CorporateCareers/jobs"},
    "capital_one": {"company": "Capital One", "endpoint": "https://capitalone.wd12.myworkdayjobs.com/wday/cxs/capitalone/Capital_One/jobs"},
    "paypal": {"company": "PayPal", "endpoint": "https://paypal.wd1.myworkdayjobs.com/wday/cxs/paypal/jobs/jobs"},
    "visa": {"company": "Visa", "endpoint": "https://visa.wd5.myworkdayjobs.com/wday/cxs/visa/Visa/jobs"},
    "citigroup": {"company": "Citi", "endpoint": "https://citi.wd5.myworkdayjobs.com/wday/cxs/citi/2/jobs"},
    "statestreet": {"company": "State Street", "endpoint": "https://statestreet.wd1.myworkdayjobs.com/wday/cxs/statestreet/Global/jobs"},
    "pnc": {"company": "PNC Financial Services", "endpoint": "https://pnc.wd5.myworkdayjobs.com/wday/cxs/pnc/External/jobs"},
    "barclays": {"company": "Barclays", "endpoint": "https://barclays.wd3.myworkdayjobs.com/wday/cxs/barclays/External_Career_Site_Barclays/jobs"},
    "morganstanley": {"company": "Morgan Stanley", "endpoint": "https://ms.wd5.myworkdayjobs.com/wday/cxs/ms/External/jobs"},
    "usbank": {"company": "U.S. Bank", "endpoint": "https://usbank.wd1.myworkdayjobs.com/wday/cxs/usbank/US_Bank_Careers/jobs"},
    "truist": {"company": "Truist Financial", "endpoint": "https://truist.wd1.myworkdayjobs.com/wday/cxs/truist/Careers/jobs"},
    "td_bank": {"company": "TD Bank", "endpoint": "https://td.wd3.myworkdayjobs.com/wday/cxs/td/TD_Bank_Careers/jobs"},
    "rbc": {"company": "RBC", "endpoint": "https://rbc.wd3.myworkdayjobs.com/wday/cxs/rbc/RBCGLOBAL1/jobs"},
    "raymond_james": {"company": "Raymond James", "endpoint": "https://raymondjames.wd1.myworkdayjobs.com/wday/cxs/raymondjames/RaymondJamesCareers/jobs"},
    "baird": {"company": "Baird", "endpoint": "https://baird.wd1.myworkdayjobs.com/wday/cxs/baird/Careers/jobs"},
    "blackstone": {"company": "Blackstone", "endpoint": "https://blackstone.wd1.myworkdayjobs.com/wday/cxs/blackstone/Blackstone_Careers/jobs"},
    "prudential": {"company": "Prudential Financial", "endpoint": "https://pru.wd5.myworkdayjobs.com/wday/cxs/pru/Careers/jobs"},
    "synchrony": {"company": "Synchrony Financial", "endpoint": "https://synchronyfinancial.wd5.myworkdayjobs.com/wday/cxs/synchronyfinancial/careers/jobs"},
    "fiserv": {"company": "Fiserv", "endpoint": "https://fiserv.wd5.myworkdayjobs.com/wday/cxs/fiserv/EXT/jobs"},
    "broadridge": {"company": "Broadridge Financial", "endpoint": "https://broadridge.wd5.myworkdayjobs.com/wday/cxs/broadridge/Careers/jobs"},
    "worldpay": {"company": "Worldpay", "endpoint": "https://worldpay.wd5.myworkdayjobs.com/wday/cxs/worldpay/Worldpay_External_Careers_Site/jobs"},
    "tsys": {"company": "Global Payments (TSYS)", "endpoint": "https://tsys.wd1.myworkdayjobs.com/wday/cxs/tsys/TSYS/jobs"},
    "mtb": {"company": "M&T Bank", "endpoint": "https://mtb.wd5.myworkdayjobs.com/wday/cxs/mtb/Campus/jobs"},
    "mufg": {"company": "MUFG Americas", "endpoint": "https://mufgub.wd3.myworkdayjobs.com/wday/cxs/mufgub/MUFG-Careers/jobs"},
    "early_warning": {"company": "Early Warning (Zelle)", "endpoint": "https://earlywarning.wd5.myworkdayjobs.com/wday/cxs/earlywarning/earlywarningcareers/jobs"},
    "hl": {"company": "Houlihan Lokey", "endpoint": "https://hl.wd1.myworkdayjobs.com/wday/cxs/hl/Lateral/jobs"},
    "lseg": {"company": "LSEG (London Stock Exchange Group)", "endpoint": "https://lseg.wd3.myworkdayjobs.com/wday/cxs/lseg/Graduate_Careers/jobs"},
    "kyriba": {"company": "Kyriba", "endpoint": "https://kyriba.wd5.myworkdayjobs.com/wday/cxs/kyriba/kyriba-careers/jobs"},
    # ── Analytics / Information Services / Research ──────────────────────
    "spgi": {"company": "S&P Global", "endpoint": "https://spgi.wd5.myworkdayjobs.com/wday/cxs/spgi/SPGI_Careers/jobs"},
    "gartner": {"company": "Gartner", "endpoint": "https://gartner.wd5.myworkdayjobs.com/wday/cxs/gartner/EXT/jobs"},
    "bloomberg_ig": {"company": "Bloomberg Industry Group", "endpoint": "https://bloomberg.wd1.myworkdayjobs.com/wday/cxs/bloomberg/Bloombergindustrygroup_External_Career_Site/jobs"},
    "merative": {"company": "Merative", "endpoint": "https://merative.wd12.myworkdayjobs.com/wday/cxs/merative/External_Career_Site/jobs"},
    "rand": {"company": "RAND Corporation", "endpoint": "https://rand.wd5.myworkdayjobs.com/wday/cxs/rand/External_Career_Site/jobs"},
    # ── Consulting / Professional Services / Defense IT ──────────────────
    "pwc_workday": {"company": "PwC", "endpoint": "https://pwc.wd3.myworkdayjobs.com/wday/cxs/pwc/Global_Experienced_Careers/jobs"},
    "boozallen": {"company": "Booz Allen Hamilton", "endpoint": "https://bah.wd1.myworkdayjobs.com/wday/cxs/bah/BAH_Jobs/jobs"},
    "parsons": {"company": "Parsons Corporation", "endpoint": "https://parsons.wd5.myworkdayjobs.com/wday/cxs/parsons/Search/jobs"},
    "accenture": {"company": "Accenture", "endpoint": "https://accenture.wd3.myworkdayjobs.com/wday/cxs/accenture/AccentureCareers/jobs"},
    "leidos": {"company": "Leidos", "endpoint": "https://leidos.wd5.myworkdayjobs.com/wday/cxs/leidos/External/jobs"},
    "guidehouse": {"company": "Guidehouse", "endpoint": "https://guidehouse.wd1.myworkdayjobs.com/wday/cxs/guidehouse/External/jobs"},
    "icf": {"company": "ICF International", "endpoint": "https://icf.wd5.myworkdayjobs.com/wday/cxs/icf/ICFExternal_Career_Site/jobs"},
    "gdit": {"company": "General Dynamics IT (GDIT)", "endpoint": "https://gdit.wd5.myworkdayjobs.com/wday/cxs/gdit/External_Career_Site/jobs"},
    "deloitte_ie": {"company": "Deloitte (Ireland)", "endpoint": "https://deloitteie.wd3.myworkdayjobs.com/wday/cxs/deloitteie/experienced_professionals/jobs"},
    "cisecurity": {"company": "Center for Internet Security", "endpoint": "https://cisecurity.wd1.myworkdayjobs.com/wday/cxs/cisecurity/CIS_External_Career_Site/jobs"},
    # ── Telecom / Media / Entertainment ──────────────────────────────────
    "tmobile": {"company": "T-Mobile", "endpoint": "https://tmobile.wd1.myworkdayjobs.com/wday/cxs/tmobile/External/jobs"},
    "comcast": {"company": "Comcast / NBCUniversal", "endpoint": "https://comcast.wd5.myworkdayjobs.com/wday/cxs/comcast/Comcast_Careers/jobs"},
    "att": {"company": "AT&T", "endpoint": "https://att.wd1.myworkdayjobs.com/wday/cxs/att/ATTGeneral/jobs"},
    "disney": {"company": "The Walt Disney Company", "endpoint": "https://disney.wd5.myworkdayjobs.com/wday/cxs/disney/disneycareer/jobs"},
    "warnerbros": {"company": "Warner Bros. Discovery", "endpoint": "https://warnerbros.wd5.myworkdayjobs.com/wday/cxs/warnerbros/global/jobs"},
    "nexstar": {"company": "Nexstar Media Group", "endpoint": "https://nexstar.wd5.myworkdayjobs.com/wday/cxs/nexstar/nexstar/jobs"},
    "dow_jones": {"company": "Dow Jones", "endpoint": "https://dowjones.wd1.myworkdayjobs.com/wday/cxs/dowjones/Dow_Jones_Career/jobs"},
    # ── Retail / Consumer / CPG ───────────────────────────────────────────
    "walmart": {"company": "Walmart", "endpoint": "https://walmart.wd5.myworkdayjobs.com/wday/cxs/walmart/WalmartExternal/jobs"},
    "target": {"company": "Target", "endpoint": "https://target.wd5.myworkdayjobs.com/wday/cxs/target/targetcareers/jobs"},
    "chewy": {"company": "Chewy", "endpoint": "https://chewy.wd5.myworkdayjobs.com/wday/cxs/chewy/External/jobs"},
    "jcrew": {"company": "J.Crew", "endpoint": "https://jcrew.wd1.myworkdayjobs.com/wday/cxs/jcrew/JCrewCareers/jobs"},
    "nike": {"company": "Nike", "endpoint": "https://nike.wd1.myworkdayjobs.com/wday/cxs/nike/nke/jobs"},
    "wawa": {"company": "Wawa", "endpoint": "https://wawa.wd1.myworkdayjobs.com/wday/cxs/wawa/careers/jobs"},
    "lkq": {"company": "LKQ Corporation", "endpoint": "https://lkqcorp.wd5.myworkdayjobs.com/wday/cxs/lkqcorp/ExternalCareerSite-LKQ/jobs"},
    "pvh": {"company": "PVH Corp (Calvin Klein/Tommy Hilfiger)", "endpoint": "https://pvh.wd1.myworkdayjobs.com/wday/cxs/pvh/PVH_Careers/jobs"},
    "mondelez": {"company": "Mondelez International", "endpoint": "https://wd3.myworkdaysite.com/wday/cxs/mdlz/External/jobs"},
    # ── Pharma / Biotech / Life Sciences ─────────────────────────────────
    "pfizer": {"company": "Pfizer", "endpoint": "https://pfizer.wd1.myworkdayjobs.com/wday/cxs/pfizer/PfizerCareers/jobs"},
    "merck": {"company": "Merck (MSD)", "endpoint": "https://msd.wd5.myworkdayjobs.com/wday/cxs/msd/SearchJobs/jobs"},
    "gsk": {"company": "GSK", "endpoint": "https://gsk.wd5.myworkdayjobs.com/wday/cxs/gsk/gskcareers/jobs"},
    "novartis": {"company": "Novartis", "endpoint": "https://novartis.wd3.myworkdayjobs.com/wday/cxs/novartis/Novartis_Careers/jobs"},
    "astrazeneca": {"company": "AstraZeneca", "endpoint": "https://astrazeneca.wd3.myworkdayjobs.com/wday/cxs/astrazeneca/Careers/jobs"},
    "sanofi": {"company": "Sanofi", "endpoint": "https://sanofi.wd3.myworkdayjobs.com/wday/cxs/sanofi/SanofiCareers/jobs"},
    "lilly": {"company": "Eli Lilly", "endpoint": "https://lilly.wd5.myworkdayjobs.com/wday/cxs/lilly/LLY/jobs"},
    "amgen": {"company": "Amgen", "endpoint": "https://amgen.wd1.myworkdayjobs.com/wday/cxs/amgen/Careers/jobs"},
    "roche": {"company": "Roche / Genentech", "endpoint": "https://roche.wd3.myworkdayjobs.com/wday/cxs/roche/ROG-A2O-GENE/jobs"},
    "biogen": {"company": "Biogen", "endpoint": "https://biibhr.wd3.myworkdayjobs.com/wday/cxs/biibhr/external/jobs"},
    "gilead": {"company": "Gilead Sciences", "endpoint": "https://gilead.wd1.myworkdayjobs.com/wday/cxs/gilead/gileadcareers/jobs"},
    "bms": {"company": "Bristol Myers Squibb", "endpoint": "https://bristolmyerssquibb.wd5.myworkdayjobs.com/wday/cxs/bristolmyerssquibb/BMS/jobs"},
    "abbott": {"company": "Abbott Laboratories", "endpoint": "https://abbott.wd5.myworkdayjobs.com/wday/cxs/abbott/abbottcareers/jobs"},
    "vertex": {"company": "Vertex Pharmaceuticals", "endpoint": "https://vrtx.wd5.myworkdayjobs.com/wday/cxs/vrtx/Vertex_Careers/jobs"},
    "stryker": {"company": "Stryker", "endpoint": "https://stryker.wd1.myworkdayjobs.com/wday/cxs/stryker/StrykerCareers/jobs"},
    "medtronic": {"company": "Medtronic", "endpoint": "https://medtronic.wd1.myworkdayjobs.com/wday/cxs/medtronic/MedtronicCareers/jobs"},
    "bdx": {"company": "Becton Dickinson (BD)", "endpoint": "https://bdx.wd1.myworkdayjobs.com/wday/cxs/bdx/EXTERNAL_CAREER_SITE_USA/jobs"},
    "diageo": {"company": "Diageo", "endpoint": "https://diageo.wd3.myworkdayjobs.com/wday/cxs/diageo/Diageo_Careers/jobs"},
    "iff": {"company": "IFF (Intl Flavors & Fragrances)", "endpoint": "https://iff.wd5.myworkdayjobs.com/wday/cxs/iff/IFF_Careers/jobs"},
    "vwr_avantor": {"company": "Avantor", "endpoint": "https://vwr.wd1.myworkdayjobs.com/wday/cxs/vwr/avantorJobs/jobs"},
    # ── Healthcare / Hospital Systems / Distribution ──────────────────────
    "cleveland_clinic": {"company": "Cleveland Clinic", "endpoint": "https://ccf.wd1.myworkdayjobs.com/wday/cxs/ccf/ClevelandClinicCareers/jobs"},
    "vanderbilt_mc": {"company": "Vanderbilt University Medical Center", "endpoint": "https://vumc.wd1.myworkdayjobs.com/wday/cxs/vumc/vumccareers/jobs"},
    "stanford_health": {"company": "Stanford Health Care", "endpoint": "https://stanfordhealthcare.wd5.myworkdayjobs.com/wday/cxs/stanfordhealthcare/UHA_External_Careers/jobs"},
    "wvu_medicine": {"company": "WVU Medicine", "endpoint": "https://wvumedicine.wd1.myworkdayjobs.com/wday/cxs/wvumedicine/WVUH/jobs"},
    "mckesson": {"company": "McKesson", "endpoint": "https://mckesson.wd3.myworkdayjobs.com/wday/cxs/mckesson/External_Careers/jobs"},
    "cencora": {"company": "Cencora (AmerisourceBergen)", "endpoint": "https://myhrabc.wd5.myworkdayjobs.com/wday/cxs/myhrabc/Global/jobs"},
    "cardinal_health": {"company": "Cardinal Health", "endpoint": "https://cardinalhealth.wd1.myworkdayjobs.com/wday/cxs/cardinalhealth/EXT/jobs"},
    "ssm_health": {"company": "SSM Health", "endpoint": "https://ssmh.wd5.myworkdayjobs.com/wday/cxs/ssmh/ssmhealth/jobs"},
    "allina": {"company": "Allina Health", "endpoint": "https://allina.wd5.myworkdayjobs.com/wday/cxs/allina/External/jobs"},
    "uofl_health": {"company": "UofL Health", "endpoint": "https://uoflhealth.wd1.myworkdayjobs.com/wday/cxs/uoflhealth/UofLHealthCareers/jobs"},
    "kansas_health": {"company": "University of Kansas Health System", "endpoint": "https://kansashealthsystem.wd1.myworkdayjobs.com/wday/cxs/kansashealthsystem/careers/jobs"},
    # ── Insurance ──────────────────────────────────────────────────────────
    "travelers": {"company": "Travelers Insurance", "endpoint": "https://travelers.wd5.myworkdayjobs.com/wday/cxs/travelers/External/jobs"},
    "njm": {"company": "NJM Insurance", "endpoint": "https://njm.wd1.myworkdayjobs.com/wday/cxs/njm/njm/jobs"},
    "allstate": {"company": "Allstate", "endpoint": "https://allstate.wd5.myworkdayjobs.com/wday/cxs/allstate/allstate_careers/jobs"},
    "thehartford": {"company": "The Hartford", "endpoint": "https://thehartford.wd5.myworkdayjobs.com/wday/cxs/thehartford/Careers_External/jobs"},
    "nationwide": {"company": "Nationwide Insurance", "endpoint": "https://nationwide.wd1.myworkdayjobs.com/wday/cxs/nationwide/Nationwide_Career/jobs"},
    "american_fidelity": {"company": "American Fidelity", "endpoint": "https://americanfidelity.wd5.myworkdayjobs.com/wday/cxs/americanfidelity/External/jobs"},
    # ── Aerospace & Defense ───────────────────────────────────────────────
    "boeing": {"company": "Boeing", "endpoint": "https://boeing.wd1.myworkdayjobs.com/wday/cxs/boeing/EXTERNAL_CAREERS/jobs"},
    "northrop": {"company": "Northrop Grumman", "endpoint": "https://ngc.wd1.myworkdayjobs.com/wday/cxs/ngc/Northrop_Grumman_External_Site/jobs"},
    "rtx": {"company": "RTX (Raytheon Technologies)", "endpoint": "https://globalhr.wd5.myworkdayjobs.com/wday/cxs/globalhr/REC_RTX_Ext_Gateway/jobs"},
    "blueorigin": {"company": "Blue Origin", "endpoint": "https://blueorigin.wd5.myworkdayjobs.com/wday/cxs/blueorigin/BlueOrigin/jobs"},
    "aero_corp": {"company": "The Aerospace Corporation", "endpoint": "https://aero.wd5.myworkdayjobs.com/wday/cxs/aero/External/jobs"},
    "pae_amentum": {"company": "Amentum", "endpoint": "https://pae.wd1.myworkdayjobs.com/wday/cxs/pae/Amentum_Careers/jobs"},
    # ── Industrial / Manufacturing / Automotive ───────────────────────────
    "jll": {"company": "JLL", "endpoint": "https://jll.wd1.myworkdayjobs.com/wday/cxs/jll/jllcareers/jobs"},
    "jci": {"company": "Johnson Controls", "endpoint": "https://jci.wd5.myworkdayjobs.com/wday/cxs/jci/JCI/jobs"},
    "caterpillar": {"company": "Caterpillar", "endpoint": "https://cat.wd5.myworkdayjobs.com/wday/cxs/cat/CaterpillarCareers/jobs"},
    "gm": {"company": "General Motors", "endpoint": "https://generalmotors.wd5.myworkdayjobs.com/wday/cxs/generalmotors/Careers_GM/jobs"},
    "toyota": {"company": "Toyota Motor North America", "endpoint": "https://toyota.wd5.myworkdayjobs.com/wday/cxs/toyota/TMNA/jobs"},
    "3m": {"company": "3M", "endpoint": "https://3m.wd1.myworkdayjobs.com/wday/cxs/3m/Search/jobs"},
    "ryder": {"company": "Ryder System", "endpoint": "https://ryder.wd5.myworkdayjobs.com/wday/cxs/ryder/RyderCareers/jobs"},
    "finning": {"company": "Finning International", "endpoint": "https://finning.wd3.myworkdayjobs.com/wday/cxs/finning/External/jobs"},
    "plexus": {"company": "Plexus Corp", "endpoint": "https://plexus.wd5.myworkdayjobs.com/wday/cxs/plexus/plexus_careers/jobs"},
    "flir": {"company": "FLIR Systems (Teledyne)", "endpoint": "https://flir.wd1.myworkdayjobs.com/wday/cxs/flir/flircareers/jobs"},
    "hntb": {"company": "HNTB Corporation", "endpoint": "https://hntb.wd5.myworkdayjobs.com/wday/cxs/hntb/HNTB_Careers/jobs"},
    "granite_construction": {"company": "Granite Construction", "endpoint": "https://granite.wd1.myworkdayjobs.com/wday/cxs/granite/careers/jobs"},
    "barry_wehmiller": {"company": "Barry-Wehmiller", "endpoint": "https://barrywehmiller.wd1.myworkdayjobs.com/wday/cxs/barrywehmiller/BWConfidential/jobs"},
    # ── Energy / Utilities / Chemicals ────────────────────────────────────
    "chevron": {"company": "Chevron", "endpoint": "https://chevron.wd5.myworkdayjobs.com/wday/cxs/chevron/jobs/jobs"},
    "duke_energy": {"company": "Duke Energy", "endpoint": "https://dukeenergy.wd1.myworkdayjobs.com/wday/cxs/dukeenergy/Search/jobs"},
    "dow": {"company": "Dow Chemical", "endpoint": "https://dow.wd1.myworkdayjobs.com/wday/cxs/dow/ExternalCareers/jobs"},
    "chemours": {"company": "Chemours", "endpoint": "https://chemours.wd5.myworkdayjobs.com/wday/cxs/chemours/Chemours/jobs"},
    "air_products": {"company": "Air Products", "endpoint": "https://airproducts.wd5.myworkdayjobs.com/wday/cxs/airproducts/AP0001/jobs"},
    "aes": {"company": "AES Corporation", "endpoint": "https://aes.wd1.myworkdayjobs.com/wday/cxs/aes/AES_US/jobs"},
    "enbridge": {"company": "Enbridge", "endpoint": "https://enbridge.wd3.myworkdayjobs.com/wday/cxs/enbridge/enbridge_careers/jobs"},
    "dupont": {"company": "DuPont", "endpoint": "https://dupontpolymer.wd5.myworkdayjobs.com/wday/cxs/dupontpolymer/Careers/jobs"},
    # ── Real Estate / Non-Profit / International ──────────────────────────
    "amh": {"company": "American Homes 4 Rent", "endpoint": "https://amh.wd12.myworkdayjobs.com/wday/cxs/amh/External_Careers/jobs"},
    "theirc": {"company": "International Rescue Committee", "endpoint": "https://theirc.wd1.myworkdayjobs.com/wday/cxs/theirc/External_Careers/jobs"},
    "cw": {"company": "Cushman & Wakefield", "endpoint": "https://cw.wd1.myworkdayjobs.com/wday/cxs/cw/External/jobs"},
    "weforum": {"company": "World Economic Forum", "endpoint": "https://weforum.wd3.myworkdayjobs.com/wday/cxs/weforum/Forum_Careers/jobs"},
    # ── Logistics / Distribution / Other ─────────────────────────────────
    "cdw": {"company": "CDW Corporation", "endpoint": "https://cdw.wd5.myworkdayjobs.com/wday/cxs/cdw/Careers/jobs"},
    "srs_distribution": {"company": "SRS Distribution", "endpoint": "https://srsdistribution.wd1.myworkdayjobs.com/wday/cxs/srsdistribution/SRS/jobs"},
    "taskus": {"company": "TaskUs", "endpoint": "https://taskus.wd1.myworkdayjobs.com/wday/cxs/taskus/Careers/jobs"},
    "asmglobal": {"company": "ASM Global", "endpoint": "https://asmglobal.wd1.myworkdayjobs.com/wday/cxs/asmglobal/careers/jobs"},
    "northeastern": {"company": "Northeastern University", "endpoint": "https://northeastern.wd1.myworkdayjobs.com/wday/cxs/northeastern/careers/jobs"},
    "amadeus": {"company": "Amadeus IT Group", "endpoint": "https://amadeus.wd502.myworkdayjobs.com/wday/cxs/amadeus/jobs/jobs"},
    "globe_telecom": {"company": "Globe Telecom", "endpoint": "https://globe.wd3.myworkdayjobs.com/wday/cxs/globe/GLB_Careers/jobs"},
}
SPONSOR_FRIENDLY_US_COMPANIES = [
    "Anthropic",
    "OpenAI",
    "Figma",
    "Notion",
    "Cohere",
    "Scale AI",
    "Runway",
    "Perplexity",
    "monday.com",
    "Databricks",
    "Ramp",
    "Rippling",
    "Plaid",
    "HubSpot",
    "Snowflake",
    "Airbnb",
    "Netflix",
    # Workday-based companies (sponsor-friendly)
    "Visa",
    "Mastercard",
    "Capital One",
    "JPMorgan Chase",
    "Salesforce",
    "Adobe",
    "CrowdStrike",
    "Palo Alto Networks",
    "Intuit",
    "Uber",
    "DoorDash",
    "ServiceNow",
    "Block",
]
CAREER_SITE_SOURCES = {"greenhouse", "lever", "workday", "ashby", "smartrecruiters", "icims", "jobvite", "taleo", "company_site"}
CAREER_SITE_COOLDOWN_DAYS = max(0, int(settings.career_site_cooldown_days or 0))


def _parse_posted_datetime(raw_job: dict) -> datetime | None:
    meta = raw_job.get("meta") or {}
    candidates = [
        str(meta.get("posted_on") or "").strip(),
        str(meta.get("published_on") or "").strip(),
    ]
    for value in candidates:
        if not value:
            continue
        lowered = value.lower()
        if lowered in {"today", "just posted"}:
            return datetime.now(timezone.utc)
        match = None
        if "day" in lowered:
            match = __import__("re").search(r"(\d+)\s+day", lowered)
            if match:
                return datetime.now(timezone.utc) - timedelta(days=int(match.group(1)))
        if "hour" in lowered:
            match = __import__("re").search(r"(\d+)\s+hour", lowered)
            if match:
                return datetime.now(timezone.utc) - timedelta(hours=int(match.group(1)))
        if "week" in lowered:
            match = __import__("re").search(r"(\d+)\s+week", lowered)
            if match:
                return datetime.now(timezone.utc) - timedelta(days=7 * int(match.group(1)))
        for parser in (
            lambda text: datetime.fromisoformat(text.replace("Z", "+00:00")),
            lambda text: datetime.strptime(text, "%Y-%m-%d"),
            lambda text: datetime.strptime(text, "%b %d, %Y"),
            lambda text: datetime.strptime(text, "%B %d, %Y"),
        ):
            try:
                parsed = parser(value)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed
            except Exception:
                continue
    return None


def _is_recent_enough(raw_job: dict, *, days: int = 7) -> bool:
    posted_at = _parse_posted_datetime(raw_job)
    if posted_at is None:
        return True
    return posted_at >= datetime.now(timezone.utc) - timedelta(days=max(1, days))


def _should_apply_company_cooldown(source: str) -> bool:
    return str(source).strip().lower() in CAREER_SITE_SOURCES


def _cooldown_employer_name(*, source: str, target_slug: str) -> str:
    return str(target_slug).strip().lower()


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        normalized = str(value or "").strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(str(value).strip())
    return ordered


async def _expand_source_targets(
    profile: dict,
    explicit: list[str] | None,
    source: str,
    *,
    db_path: Path | None = None,
    company_pool: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    normalized_source = str(source or "").strip().lower()
    if explicit:
        if normalized_source == "workday":
            resolved: list[dict[str, str]] = []
            for target in explicit:
                target_spec = _resolve_workday_target(target)
                if not target_spec["endpoint"]:
                    continue
                resolved.append(
                    {
                        "company": target_spec["company"],
                        "target": target_spec["endpoint"],
                        "careers_url": target_spec["endpoint"],
                        "official_domain": "",
                    }
                )
            return resolved
        return [{"company": str(target).strip(), "target": str(target).strip(), "careers_url": "", "official_domain": ""} for target in _dedupe(explicit)]

    active_pool = company_pool or []
    companies = [str(record.get("company") or "").strip() for record in active_pool]
    companies.extend(SPONSOR_FRIENDLY_US_COMPANIES)
    discovered = await discover_company_targets(companies, source=normalized_source, db_path=db_path)
    if normalized_source == "workday":
        static_workday_targets = [
            {
                "company": config["company"],
                "target": config["endpoint"],
                "careers_url": config["endpoint"],
                "official_domain": "",
            }
            for config in WORKDAY_DISCOVERY_MAP.values()
        ]
        combined = static_workday_targets + discovered
    else:
        combined = discovered

    ordered: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in combined:
        target = str(item.get("target") or "").strip()
        if not target or target.lower() in seen:
            continue
        seen.add(target.lower())
        ordered.append(item)
    return ordered


def _resolve_workday_target(target: str) -> dict[str, str]:
    normalized = str(target or "").strip().lower()
    if normalized in WORKDAY_DISCOVERY_MAP:
        return {
            "company": WORKDAY_DISCOVERY_MAP[normalized]["company"],
            "endpoint": WORKDAY_DISCOVERY_MAP[normalized]["endpoint"],
            "key": normalized,
        }
    # Try common alternative normalizations (spaces -> underscores, remove spaces)
    alt_underscore = normalized.replace(" ", "_")
    alt_nospace = normalized.replace(" ", "")
    for alt in (alt_underscore, alt_nospace):
        if alt in WORKDAY_DISCOVERY_MAP:
            return {
                "company": WORKDAY_DISCOVERY_MAP[alt]["company"],
                "endpoint": WORKDAY_DISCOVERY_MAP[alt]["endpoint"],
                "key": alt,
            }
    if str(target or "").strip().lower().startswith("http"):
        return {
            "company": str(target).strip(),
            "endpoint": str(target).strip(),
            "key": str(target).strip().lower(),
        }
    return {"company": str(target).strip(), "endpoint": "", "key": normalized}


async def run_job_scout(
    greenhouse_companies: list[str] | None = None,
    lever_companies: list[str] | None = None,
    workday_companies: list[str] | None = None,
    ashby_companies: list[str] | None = None,
    jobvite_companies: list[str] | None = None,
    smartrecruiters_companies: list[str] | None = None,
    icims_companies: list[str] | None = None,
    linkedin_keywords: list[str] | None = None,
    linkedin_location: str = "",
    indeed_keywords: list[str] | None = None,
    indeed_location: str = "",
    glassdoor_keywords: list[str] | None = None,
    glassdoor_location: str = "",
    limit_per_source: int = 20,
    db_path: Path | None = None,
) -> dict:
    active_db_path = db_path or Path(settings.database_path)
    profile = load_profile()
    daily_target = max(1, int(settings.company_daily_target_count or 200))
    company_pool_selection = select_company_search_pool(profile, limit=daily_target, advance_cursor=True)
    company_pool = company_pool_selection["companies"]
    greenhouse_targets = await _expand_source_targets(
        profile,
        greenhouse_companies,
        "greenhouse",
        db_path=active_db_path,
        company_pool=company_pool,
    )
    lever_targets = await _expand_source_targets(
        profile,
        lever_companies,
        "lever",
        db_path=active_db_path,
        company_pool=company_pool,
    )
    workday_targets = await _expand_source_targets(
        profile,
        workday_companies,
        "workday",
        db_path=active_db_path,
        company_pool=company_pool,
    )
    ashby_targets = await _expand_source_targets(profile, ashby_companies, "ashby", db_path=active_db_path, company_pool=company_pool)
    smartrecruiters_targets = await _expand_source_targets(
        profile,
        smartrecruiters_companies,
        "smartrecruiters",
        db_path=active_db_path,
        company_pool=company_pool,
    )
    icims_targets = await _expand_source_targets(profile, icims_companies, "icims", db_path=active_db_path, company_pool=company_pool)
    jobvite_targets = await _expand_source_targets(profile, jobvite_companies, "jobvite", db_path=active_db_path, company_pool=company_pool)
    taleo_targets = await _expand_source_targets(profile, None, "taleo", db_path=active_db_path, company_pool=company_pool)
    fetch_limit = max(limit_per_source * 10, 25)
    excluded_companies = {normalize_company_name(company) for company in profile.get("excluded_companies", [])}
    needs_visa = bool(profile.get("visa_sponsorship", False))

    raw_jobs: list[dict] = []
    skipped_companies_due_to_cooldown = 0
    for target in greenhouse_targets:
        company_name = str(target.get("company") or "").strip()
        slug = str(target.get("target") or "").strip()
        careers_url = str(target.get("careers_url") or f"https://boards.greenhouse.io/{slug}").strip()
        normalized_company = normalize_company_name(company_name)
        cooldown_company = _cooldown_employer_name(source="greenhouse", target_slug=company_name or slug)
        if normalized_company in excluded_companies or not slug:
            continue
        if _should_apply_company_cooldown("greenhouse") and company_source_scanned_recently(
            cooldown_company,
            "career_site",
            cooldown_days=CAREER_SITE_COOLDOWN_DAYS,
            db_path=active_db_path,
        ):
            skipped_companies_due_to_cooldown += 1
            continue
        fetched_jobs = await fetch_greenhouse_jobs(slug, limit=fetch_limit)
        if company_name:
            for job in fetched_jobs:
                job["company"] = company_name
        raw_jobs.extend(fetched_jobs)
        record_company_source_scan(
            cooldown_company,
            "career_site",
            source_url=careers_url,
            db_path=active_db_path,
        )
    for target in lever_targets:
        company_name = str(target.get("company") or "").strip()
        slug = str(target.get("target") or "").strip()
        careers_url = str(target.get("careers_url") or f"https://jobs.lever.co/{slug}").strip()
        normalized_company = normalize_company_name(company_name)
        cooldown_company = _cooldown_employer_name(source="lever", target_slug=company_name or slug)
        if normalized_company in excluded_companies or not slug:
            continue
        if _should_apply_company_cooldown("lever") and company_source_scanned_recently(
            cooldown_company,
            "career_site",
            cooldown_days=CAREER_SITE_COOLDOWN_DAYS,
            db_path=active_db_path,
        ):
            skipped_companies_due_to_cooldown += 1
            continue
        fetched_jobs = await fetch_lever_jobs(slug, limit=fetch_limit)
        if company_name:
            for job in fetched_jobs:
                job["company"] = company_name
        raw_jobs.extend(fetched_jobs)
        record_company_source_scan(
            cooldown_company,
            "career_site",
            source_url=careers_url,
            db_path=active_db_path,
        )
    for target in workday_targets:
        target_spec = _resolve_workday_target(str(target.get("target") or ""))
        if str(target.get("company") or "").strip():
            target_spec["company"] = str(target.get("company") or "").strip()
        if not target_spec["endpoint"]:
            continue
        cooldown_company = _cooldown_employer_name(source="workday", target_slug=target_spec["company"] or target_spec["key"])
        normalized_company = normalize_company_name(target_spec["company"])
        if normalized_company in excluded_companies:
            continue
        if _should_apply_company_cooldown("workday") and company_source_scanned_recently(
            cooldown_company,
            "career_site",
            cooldown_days=CAREER_SITE_COOLDOWN_DAYS,
            db_path=active_db_path,
        ):
            skipped_companies_due_to_cooldown += 1
            continue
        fetched_jobs = await fetch_workday_jobs(
            company=target_spec["company"],
            endpoint=target_spec["endpoint"],
            limit=fetch_limit,
        )
        raw_jobs.extend(fetched_jobs)
        record_company_source_scan(
            cooldown_company,
            "career_site",
            source_url=target_spec["endpoint"],
            db_path=active_db_path,
        )
    for target in ashby_targets:
        company_name = str(target.get("company") or "").strip()
        board_url = str(target.get("target") or "").strip()
        normalized_company = normalize_company_name(company_name)
        cooldown_company = _cooldown_employer_name(source="ashby", target_slug=company_name or board_url)
        if normalized_company in excluded_companies or not board_url:
            continue
        if _should_apply_company_cooldown("ashby") and company_source_scanned_recently(
            cooldown_company,
            "career_site",
            cooldown_days=CAREER_SITE_COOLDOWN_DAYS,
            db_path=active_db_path,
        ):
            skipped_companies_due_to_cooldown += 1
            continue
        fetched_jobs = await fetch_ashby_jobs(board_url, limit=fetch_limit)
        if company_name:
            for job in fetched_jobs:
                job["company"] = company_name
        raw_jobs.extend(fetched_jobs)
        record_company_source_scan(
            cooldown_company,
            "career_site",
            source_url=str(target.get("careers_url") or board_url),
            db_path=active_db_path,
        )
    for target in smartrecruiters_targets:
        company_name = str(target.get("company") or "").strip()
        board_url = str(target.get("target") or "").strip()
        normalized_company = normalize_company_name(company_name)
        cooldown_company = _cooldown_employer_name(source="smartrecruiters", target_slug=company_name or board_url)
        if normalized_company in excluded_companies or not board_url:
            continue
        if _should_apply_company_cooldown("smartrecruiters") and company_source_scanned_recently(
            cooldown_company,
            "career_site",
            cooldown_days=CAREER_SITE_COOLDOWN_DAYS,
            db_path=active_db_path,
        ):
            skipped_companies_due_to_cooldown += 1
            continue
        fetched_jobs = await fetch_smartrecruiters_jobs(board_url, limit=fetch_limit)
        if company_name:
            for job in fetched_jobs:
                job["company"] = company_name
        raw_jobs.extend(fetched_jobs)
        record_company_source_scan(
            cooldown_company,
            "career_site",
            source_url=str(target.get("careers_url") or board_url),
            db_path=active_db_path,
        )
    for target in icims_targets:
        company_name = str(target.get("company") or "").strip()
        board_url = str(target.get("target") or "").strip()
        normalized_company = normalize_company_name(company_name)
        cooldown_company = _cooldown_employer_name(source="icims", target_slug=company_name or board_url)
        if normalized_company in excluded_companies or not board_url:
            continue
        if _should_apply_company_cooldown("icims") and company_source_scanned_recently(
            cooldown_company,
            "career_site",
            cooldown_days=CAREER_SITE_COOLDOWN_DAYS,
            db_path=active_db_path,
        ):
            skipped_companies_due_to_cooldown += 1
            continue
        fetched_jobs = await fetch_icims_jobs(board_url, limit=fetch_limit)
        if company_name:
            for job in fetched_jobs:
                job["company"] = company_name
        raw_jobs.extend(fetched_jobs)
        record_company_source_scan(
            cooldown_company,
            "career_site",
            source_url=str(target.get("careers_url") or board_url),
            db_path=active_db_path,
        )
    for target in jobvite_targets:
        company_name = str(target.get("company") or "").strip()
        board_url = str(target.get("target") or "").strip()
        normalized_company = normalize_company_name(company_name)
        cooldown_company = _cooldown_employer_name(source="jobvite", target_slug=company_name or board_url)
        if normalized_company in excluded_companies or not board_url:
            continue
        if _should_apply_company_cooldown("jobvite") and company_source_scanned_recently(
            cooldown_company,
            "career_site",
            cooldown_days=CAREER_SITE_COOLDOWN_DAYS,
            db_path=active_db_path,
        ):
            skipped_companies_due_to_cooldown += 1
            continue
        fetched_jobs = await fetch_jobvite_jobs(board_url, limit=fetch_limit)
        if company_name:
            for job in fetched_jobs:
                job["company"] = company_name
        raw_jobs.extend(fetched_jobs)
        record_company_source_scan(
            cooldown_company,
            "career_site",
            source_url=str(target.get("careers_url") or board_url),
            db_path=active_db_path,
        )
    for target in taleo_targets:
        company_name = str(target.get("company") or "").strip()
        board_url = str(target.get("target") or "").strip()
        normalized_company = normalize_company_name(company_name)
        cooldown_company = _cooldown_employer_name(source="taleo", target_slug=company_name or board_url)
        if normalized_company in excluded_companies or not board_url:
            continue
        if _should_apply_company_cooldown("taleo") and company_source_scanned_recently(
            cooldown_company,
            "career_site",
            cooldown_days=CAREER_SITE_COOLDOWN_DAYS,
            db_path=active_db_path,
        ):
            skipped_companies_due_to_cooldown += 1
            continue
        try:
            fetched_jobs = await fetch_taleo_jobs(board_url, limit=fetch_limit)
        except Exception as exc:
            log.warning("Taleo fetch failed for %s: %s", company_name or board_url, exc)
            fetched_jobs = []
        if company_name:
            for job in fetched_jobs:
                job["company"] = company_name
        raw_jobs.extend(fetched_jobs)
        record_company_source_scan(
            cooldown_company,
            "career_site",
            source_url=str(target.get("careers_url") or board_url),
            db_path=active_db_path,
        )

    if linkedin_keywords:
        fetched_jobs = await fetch_linkedin_jobs(
            keywords=linkedin_keywords,
            location=linkedin_location,
            limit=fetch_limit,
        )
        raw_jobs.extend(fetched_jobs)

    if indeed_keywords:
        fetched_jobs = await fetch_indeed_jobs(
            keywords=indeed_keywords,
            location=indeed_location,
            limit=fetch_limit,
        )
        raw_jobs.extend(fetched_jobs)

    if glassdoor_keywords:
        fetched_jobs = await fetch_glassdoor_jobs(
            keywords=glassdoor_keywords,
            location=glassdoor_location,
            limit=fetch_limit,
        )
        raw_jobs.extend(fetched_jobs)

    MAX_JOBS_PER_COMPANY = 8  # Don't queue more than this many jobs at one company

    inserted = 0
    skipped = 0
    skipped_company_cap = 0
    skipped_title_dedup = 0
    records: list[JobRecord] = []
    # Track per-company counts within this batch (on top of DB counts)
    batch_company_counts: dict[str, int] = {}

    for raw in raw_jobs:
        if not _is_recent_enough(raw, days=10):
            skipped += 1
            continue

        company = str(raw.get("company", "") or "").strip()
        title = str(raw.get("title", "") or "").strip()
        company_lower = company.lower()

        # Per-company cap: check DB + batch count
        if company_lower:
            db_count = count_company_active_jobs(company, db_path=active_db_path)
            batch_count = batch_company_counts.get(company_lower, 0)
            if db_count + batch_count >= MAX_JOBS_PER_COMPANY:
                skipped_company_cap += 1
                skipped += 1
                continue

        # Title dedup: skip if we already applied to same company+title (any location)
        if company and title and has_applied_to_title(company, title, db_path=active_db_path):
            skipped_title_dedup += 1
            skipped += 1
            continue

        score = match_job(
            raw.get("jd_text", ""),
            profile,
            title=raw.get("title", ""),
            location=raw.get("location", ""),
            company=raw.get("company", ""),
            url=raw.get("url", ""),
        )
        record = JobRecord(
            id=make_job_id(raw.get("company", "") or "", raw.get("title", "") or "", raw.get("location", "") or ""),
            title=raw.get("title", "") or "",
            company=raw.get("company", "") or "",
            location=raw.get("location", "") or "",
            url=raw.get("url", "") or "",
            source=raw.get("source", "") or "",
            jd_text=raw.get("jd_text", "") or "",
            match_score=score["match_score"],
            match_reasons=score["match_reasons"],
            top_keywords=score["top_keywords"],
            role_bucket=score["role_bucket"],
            visa_sponsorship_likely=score["visa_sponsorship_likely"],
            visa_sponsorship_blocked=score["visa_sponsorship_blocked"],
            date_found=utc_today(),
            status="new",
            source_urls=raw.get("source_urls", []),
            meta=raw.get("meta", {}),
        )
        if record.match_score < float(profile.get("min_match_score", 0.75)):
            skipped += 1
            continue
        if needs_visa and record.visa_sponsorship_blocked:
            skipped += 1
            continue

        if upsert_job(record, db_path=active_db_path):
            inserted += 1
            records.append(record)
            batch_company_counts[company_lower] = batch_company_counts.get(company_lower, 0) + 1
        else:
            skipped += 1

    return {
        "company_pool_count": len(company_pool),
        "company_pool_preview": [str(record.get("company") or "").strip() for record in company_pool[:10]],
        "rotating_company_preview": company_pool_selection.get("rotating_preview", []),
        "company_rotation_state": company_pool_selection.get("cursor_state", {}),
        "company_rotation_start": company_pool_selection.get("rotation_start", {}),
        "fetched": len(raw_jobs),
        "inserted": inserted,
        "skipped": skipped,
        "skipped_companies_due_to_cooldown": skipped_companies_due_to_cooldown,
        "skipped_company_cap": skipped_company_cap,
        "skipped_title_dedup": skipped_title_dedup,
        "jobs": records,
    }
