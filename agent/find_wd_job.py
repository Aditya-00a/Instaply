"""Find an active Workday job URL from a tenant endpoint."""
import asyncio, httpx, json

TENANTS = [
    ("Autodesk", "https://autodesk.wd1.myworkdayjobs.com/wday/cxs/autodesk/Ext/jobs",
     "https://autodesk.wd1.myworkdayjobs.com/en-US/Ext"),
    ("Applied Materials", "https://amat.wd1.myworkdayjobs.com/wday/cxs/amat/External/jobs",
     "https://amat.wd1.myworkdayjobs.com/en-US/External"),
    ("Motorola Solutions", "https://motorolasolutions.wd5.myworkdayjobs.com/wday/cxs/motorolasolutions/Careers/jobs",
     "https://motorolasolutions.wd5.myworkdayjobs.com/en-US/Careers"),
    ("Broadcom", "https://broadcom.wd1.myworkdayjobs.com/wday/cxs/broadcom/External_Career/jobs",
     "https://broadcom.wd1.myworkdayjobs.com/en-US/External_Career"),
]

async def fetch(name, endpoint, base):
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(endpoint, json={"searchText": "analyst", "limit": 20, "offset": 0})
        if r.status_code != 200:
            return name, None
        data = r.json()
        for job in data.get("jobPostings", []):
            url = base + job.get("externalPath", "")
            title = job.get("title", "")
            loc = job.get("locationsText", "")
            return name, (title, loc, url)
    return name, None

async def main():
    for name, endpoint, base in TENANTS:
        try:
            _, result = await fetch(name, endpoint, base)
            if result:
                print(f"[{name}]  {result[0]}  |  {result[1]}")
                print(f"    URL: {result[2]}\n")
        except Exception as e:
            print(f"[{name}] ERROR: {e}")

asyncio.run(main())
