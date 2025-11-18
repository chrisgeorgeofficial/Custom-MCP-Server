import asyncio
import os
from typing import Any, Optional
from datetime import datetime, timedelta
import httpx
from mcp.server.models import InitializationOptions
from mcp.server import NotificationOptions, Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ImageContent, EmbeddedResource
import mcp.types as types

# LinkedIn API Configuration
LINKEDIN_API_BASE = "https://api.linkedin.com/v2"
CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID")
CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET")
ACCESS_TOKEN = os.getenv("LINKEDIN_ACCESS_TOKEN")

class LinkedInMCPServer:
    def __init__(self):
        self.server = Server("linkedin-mcp-server")
        self.http_client = httpx.AsyncClient()
        self.access_token = ACCESS_TOKEN
        
        # Register handlers
        self._setup_handlers()
    
    def _setup_handlers(self):
        @self.server.list_tools()
        async def handle_list_tools() -> list[Tool]:
            return [
                Tool(
                    name="search_jobs",
                    description="Search for job postings on LinkedIn. Can filter by keywords, location, experience level, and recency.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "keywords": {
                                "type": "string",
                                "description": "Job search keywords (e.g., 'AI Engineer', 'Machine Learning', 'Data Scientist')"
                            },
                            "location": {
                                "type": "string",
                                "description": "Location for the job search (e.g., 'San Francisco', 'Remote', 'India')"
                            },
                            "experience_level": {
                                "type": "string",
                                "enum": ["entry", "associate", "mid-senior", "director", "executive"],
                                "description": "Experience level filter"
                            },
                            "posted_within_days": {
                                "type": "integer",
                                "description": "Filter jobs posted within last N days (e.g., 7 for last week)",
                                "default": 30
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of results to return",
                                "default": 10
                            }
                        },
                        "required": ["keywords"]
                    }
                ),
                Tool(
                    name="get_job_details",
                    description="Get detailed information about a specific job posting",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "job_id": {
                                "type": "string",
                                "description": "LinkedIn job posting ID"
                            }
                        },
                        "required": ["job_id"]
                    }
                ),
                Tool(
                    name="search_companies",
                    description="Search for companies on LinkedIn",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "company_name": {
                                "type": "string",
                                "description": "Company name to search for"
                            },
                            "industry": {
                                "type": "string",
                                "description": "Industry filter (optional)"
                            },
                            "location": {
                                "type": "string",
                                "description": "Location filter (optional)"
                            }
                        },
                        "required": ["company_name"]
                    }
                ),
                Tool(
                    name="get_company_details",
                    description="Get detailed information about a company including size, industry, description, and recent updates",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "company_id": {
                                "type": "string",
                                "description": "LinkedIn company ID or universal name"
                            }
                        },
                        "required": ["company_id"]
                    }
                ),
                Tool(
                    name="search_profiles",
                    description="Search for people/profiles on LinkedIn",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "keywords": {
                                "type": "string",
                                "description": "Search keywords (name, title, skills, etc.)"
                            },
                            "current_company": {
                                "type": "string",
                                "description": "Filter by current company"
                            },
                            "location": {
                                "type": "string",
                                "description": "Location filter"
                            }
                        },
                        "required": ["keywords"]
                    }
                ),
                Tool(
                    name="get_company_jobs",
                    description="Get all active job postings from a specific company",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "company_id": {
                                "type": "string",
                                "description": "LinkedIn company ID"
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of jobs to return",
                                "default": 20
                            }
                        },
                        "required": ["company_id"]
                    }
                ),
                Tool(
                    name="analyze_job_market",
                    description="Analyze job market trends for specific keywords/roles including count of postings, common requirements, and salary insights",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "role": {
                                "type": "string",
                                "description": "Job role to analyze (e.g., 'AI Engineer', 'Data Scientist')"
                            },
                            "location": {
                                "type": "string",
                                "description": "Location for analysis"
                            }
                        },
                        "required": ["role"]
                    }
                )
            ]
        
        @self.server.call_tool()
        async def handle_call_tool(
            name: str, arguments: dict | None
        ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
            try:
                if name == "search_jobs":
                    result = await self._search_jobs(arguments)
                elif name == "get_job_details":
                    result = await self._get_job_details(arguments)
                elif name == "search_companies":
                    result = await self._search_companies(arguments)
                elif name == "get_company_details":
                    result = await self._get_company_details(arguments)
                elif name == "search_profiles":
                    result = await self._search_profiles(arguments)
                elif name == "get_company_jobs":
                    result = await self._get_company_jobs(arguments)
                elif name == "analyze_job_market":
                    result = await self._analyze_job_market(arguments)
                else:
                    raise ValueError(f"Unknown tool: {name}")
                
                return [types.TextContent(type="text", text=result)]
            except Exception as e:
                return [types.TextContent(type="text", text=f"Error: {str(e)}")]
    
    async def _make_request(self, endpoint: str, params: dict = None) -> dict:
        """Make authenticated request to LinkedIn API"""
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "X-Restli-Protocol-Version": "2.0.0"
        }
        
        url = f"{LINKEDIN_API_BASE}{endpoint}"
        response = await self.http_client.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()
    
    async def _search_jobs(self, args: dict) -> str:
        """Search for jobs with filters"""
        keywords = args.get("keywords")
        location = args.get("location", "")
        experience_level = args.get("experience_level", "")
        posted_within_days = args.get("posted_within_days", 30)
        limit = args.get("limit", 10)
        
        # Calculate date filter
        cutoff_date = datetime.now() - timedelta(days=posted_within_days)
        
        # Build search parameters
        params = {
            "keywords": keywords,
            "location": location,
            "f_E": self._map_experience_level(experience_level),
            "f_TPR": f"r{posted_within_days * 86400}",  # Time posted in seconds
            "count": limit
        }
        
        # Make API request
        data = await self._make_request("/jobSearch", params)
        
        # Format results
        jobs = data.get("elements", [])
        if not jobs:
            return f"No jobs found for '{keywords}' in {location or 'any location'}"
        
        result = f"Found {len(jobs)} jobs for '{keywords}'"
        if location:
            result += f" in {location}"
        if experience_level:
            result += f" ({experience_level} level)"
        result += f" posted within last {posted_within_days} days:\n\n"
        
        for i, job in enumerate(jobs, 1):
            company = job.get("companyDetails", {}).get("company", "Unknown Company")
            title = job.get("title", "Unknown Title")
            location_str = job.get("formattedLocation", "Location not specified")
            job_id = job.get("jobPostingId", "")
            posted_date = job.get("listedAt", "")
            
            result += f"{i}. {title}\n"
            result += f"   Company: {company}\n"
            result += f"   Location: {location_str}\n"
            result += f"   Job ID: {job_id}\n"
            result += f"   Posted: {self._format_date(posted_date)}\n"
            result += f"   URL: https://www.linkedin.com/jobs/view/{job_id}\n\n"
        
        return result
    
    async def _get_job_details(self, args: dict) -> str:
        """Get detailed information about a job"""
        job_id = args.get("job_id")
        
        data = await self._make_request(f"/jobs/{job_id}")
        
        title = data.get("title", "N/A")
        company = data.get("companyDetails", {}).get("company", "N/A")
        location = data.get("formattedLocation", "N/A")
        description = data.get("description", {}).get("text", "No description")
        employment_type = data.get("employmentType", "N/A")
        seniority_level = data.get("seniorityLevel", "N/A")
        industries = ", ".join(data.get("industries", []))
        
        result = f"Job Details:\n\n"
        result += f"Title: {title}\n"
        result += f"Company: {company}\n"
        result += f"Location: {location}\n"
        result += f"Employment Type: {employment_type}\n"
        result += f"Seniority Level: {seniority_level}\n"
        result += f"Industries: {industries}\n\n"
        result += f"Description:\n{description}\n"
        
        return result
    
    async def _search_companies(self, args: dict) -> str:
        """Search for companies"""
        company_name = args.get("company_name")
        industry = args.get("industry", "")
        location = args.get("location", "")
        
        params = {
            "keywords": company_name,
            "industry": industry,
            "location": location
        }
        
        data = await self._make_request("/companySearch", params)
        companies = data.get("elements", [])
        
        if not companies:
            return f"No companies found matching '{company_name}'"
        
        result = f"Found {len(companies)} companies:\n\n"
        for i, company in enumerate(companies, 1):
            name = company.get("localizedName", "Unknown")
            company_id = company.get("id", "")
            tagline = company.get("tagline", {}).get("text", "")
            
            result += f"{i}. {name}\n"
            result += f"   Company ID: {company_id}\n"
            result += f"   Tagline: {tagline}\n\n"
        
        return result
    
    async def _get_company_details(self, args: dict) -> str:
        """Get detailed company information"""
        company_id = args.get("company_id")
        
        data = await self._make_request(f"/organizations/{company_id}")
        
        name = data.get("localizedName", "N/A")
        description = data.get("description", {}).get("text", "No description")
        industry = data.get("industries", ["N/A"])[0] if data.get("industries") else "N/A"
        company_size = data.get("staffCount", "N/A")
        founded = data.get("foundedOn", {}).get("year", "N/A")
        website = data.get("websiteUrl", "N/A")
        
        result = f"Company Details:\n\n"
        result += f"Name: {name}\n"
        result += f"Industry: {industry}\n"
        result += f"Company Size: {company_size} employees\n"
        result += f"Founded: {founded}\n"
        result += f"Website: {website}\n\n"
        result += f"Description:\n{description}\n"
        
        return result
    
    async def _search_profiles(self, args: dict) -> str:
        """Search for people profiles"""
        keywords = args.get("keywords")
        current_company = args.get("current_company", "")
        location = args.get("location", "")
        
        params = {
            "keywords": keywords,
            "currentCompany": current_company,
            "location": location
        }
        
        data = await self._make_request("/peopleSearch", params)
        profiles = data.get("elements", [])
        
        if not profiles:
            return f"No profiles found matching '{keywords}'"
        
        result = f"Found {len(profiles)} profiles:\n\n"
        for i, profile in enumerate(profiles, 1):
            name = f"{profile.get('firstName', '')} {profile.get('lastName', '')}"
            headline = profile.get("headline", "")
            location_str = profile.get("locationName", "")
            
            result += f"{i}. {name}\n"
            result += f"   Headline: {headline}\n"
            result += f"   Location: {location_str}\n\n"
        
        return result
    
    async def _get_company_jobs(self, args: dict) -> str:
        """Get all jobs from a company"""
        company_id = args.get("company_id")
        limit = args.get("limit", 20)
        
        params = {
            "companyId": company_id,
            "count": limit
        }
        
        data = await self._make_request("/jobSearch", params)
        jobs = data.get("elements", [])
        
        if not jobs:
            return f"No active job postings found for this company"
        
        result = f"Found {len(jobs)} active job postings:\n\n"
        for i, job in enumerate(jobs, 1):
            title = job.get("title", "Unknown Title")
            location = job.get("formattedLocation", "N/A")
            job_id = job.get("jobPostingId", "")
            
            result += f"{i}. {title}\n"
            result += f"   Location: {location}\n"
            result += f"   Job ID: {job_id}\n"
            result += f"   URL: https://www.linkedin.com/jobs/view/{job_id}\n\n"
        
        return result
    
    async def _analyze_job_market(self, args: dict) -> str:
        """Analyze job market trends"""
        role = args.get("role")
        location = args.get("location", "")
        
        # Search for jobs to analyze
        params = {
            "keywords": role,
            "location": location,
            "count": 100
        }
        
        data = await self._make_request("/jobSearch", params)
        jobs = data.get("elements", [])
        
        if not jobs:
            return f"No data available for '{role}' analysis"
        
        # Analyze the data
        total_jobs = len(jobs)
        experience_levels = {}
        companies = {}
        locations = {}
        
        for job in jobs:
            level = job.get("seniorityLevel", "Unknown")
            experience_levels[level] = experience_levels.get(level, 0) + 1
            
            company = job.get("companyDetails", {}).get("company", "Unknown")
            companies[company] = companies.get(company, 0) + 1
            
            loc = job.get("formattedLocation", "Unknown")
            locations[loc] = locations.get(loc, 0) + 1
        
        result = f"Job Market Analysis for '{role}'"
        if location:
            result += f" in {location}"
        result += f":\n\n"
        result += f"Total Job Postings: {total_jobs}\n\n"
        
        result += "Experience Level Distribution:\n"
        for level, count in sorted(experience_levels.items(), key=lambda x: x[1], reverse=True):
            result += f"  - {level}: {count} ({count/total_jobs*100:.1f}%)\n"
        
        result += f"\nTop Hiring Companies:\n"
        for company, count in sorted(companies.items(), key=lambda x: x[1], reverse=True)[:10]:
            result += f"  - {company}: {count} openings\n"
        
        result += f"\nTop Locations:\n"
        for loc, count in sorted(locations.items(), key=lambda x: x[1], reverse=True)[:10]:
            result += f"  - {loc}: {count} openings\n"
        
        return result
    
    def _map_experience_level(self, level: str) -> str:
        """Map experience level to LinkedIn API codes"""
        mapping = {
            "entry": "1,2",
            "associate": "3",
            "mid-senior": "4",
            "director": "5",
            "executive": "6"
        }
        return mapping.get(level, "")
    
    def _format_date(self, timestamp: int) -> str:
        """Format timestamp to readable date"""
        if not timestamp:
            return "Unknown"
        dt = datetime.fromtimestamp(timestamp / 1000)
        return dt.strftime("%Y-%m-%d")
    
    async def run(self):
        """Run the MCP server"""
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="linkedin-mcp-server",
                    server_version="1.0.0",
                    capabilities=self.server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )

async def main():
    server = LinkedInMCPServer()
    await server.run()

if __name__ == "__main__":
    asyncio.run(main())