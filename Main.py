import asyncio
import os
from typing import Any, Optional
from datetime import datetime, timedelta
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlencode, quote_plus
from mcp.server.models import InitializationOptions
from mcp.server import NotificationOptions, Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
import mcp.types as types
import json
import re

class LinkedInMCPServer:
    def __init__(self):
        self.server = Server("linkedin-mcp-server")
        self.http_client = httpx.AsyncClient(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
            follow_redirects=True,
            timeout=30.0
        )
        self._setup_handlers()
    
    def _setup_handlers(self):
        @self.server.list_tools()
        async def handle_list_tools() -> list[Tool]:
            return [
                Tool(
                    name="search_jobs",
                    description="Search for job postings on LinkedIn. Can filter by keywords, location, experience level, and recency. Works without API keys by scraping public job listings.",
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
                                "enum": ["internship", "entry_level", "associate", "mid_senior", "director", "executive"],
                                "description": "Experience level: internship, entry_level (0-2 yrs), associate (2-5 yrs), mid_senior, director, executive"
                            },
                            "posted_time": {
                                "type": "string",
                                "enum": ["past_24h", "past_week", "past_month", "any_time"],
                                "description": "When the job was posted",
                                "default": "past_month"
                            },
                            "job_type": {
                                "type": "string",
                                "enum": ["full_time", "part_time", "contract", "temporary", "internship", "volunteer"],
                                "description": "Type of employment"
                            },
                            "remote": {
                                "type": "boolean",
                                "description": "Filter for remote jobs only"
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of results to return",
                                "default": 25
                            }
                        },
                        "required": ["keywords"]
                    }
                ),
                Tool(
                    name="get_job_details",
                    description="Get detailed information about a specific LinkedIn job posting using its job ID or URL",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "job_url_or_id": {
                                "type": "string",
                                "description": "LinkedIn job URL or job ID (e.g., 'https://www.linkedin.com/jobs/view/3812345678' or just '3812345678')"
                            }
                        },
                        "required": ["job_url_or_id"]
                    }
                ),
                Tool(
                    name="search_companies",
                    description="Search for companies on LinkedIn by name",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "company_name": {
                                "type": "string",
                                "description": "Company name to search for"
                            }
                        },
                        "required": ["company_name"]
                    }
                ),
                Tool(
                    name="get_company_jobs",
                    description="Get all active job postings from a specific company",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "company_name": {
                                "type": "string",
                                "description": "Company name (e.g., 'Google', 'Microsoft')"
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of jobs to return",
                                "default": 25
                            }
                        },
                        "required": ["company_name"]
                    }
                ),
                Tool(
                    name="analyze_job_market",
                    description="Analyze job market trends for specific roles including posting counts, top companies, and location distribution",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "role": {
                                "type": "string",
                                "description": "Job role to analyze (e.g., 'AI Engineer', 'Data Scientist')"
                            },
                            "location": {
                                "type": "string",
                                "description": "Location for analysis (optional)"
                            }
                        },
                        "required": ["role"]
                    }
                )
            ]
        
        @self.server.call_tool()
        async def handle_call_tool(
            name: str, arguments: dict | None
        ) -> list[types.TextContent]:
            try:
                if name == "search_jobs":
                    result = await self._search_jobs(arguments)
                elif name == "get_job_details":
                    result = await self._get_job_details(arguments)
                elif name == "search_companies":
                    result = await self._search_companies(arguments)
                elif name == "get_company_jobs":
                    result = await self._get_company_jobs(arguments)
                elif name == "analyze_job_market":
                    result = await self._analyze_job_market(arguments)
                else:
                    raise ValueError(f"Unknown tool: {name}")
                
                return [types.TextContent(type="text", text=result)]
            except Exception as e:
                return [types.TextContent(type="text", text=f"Error: {str(e)}\n\nPlease try again or adjust your search criteria.")]
    
    async def _search_jobs(self, args: dict) -> str:
        """Search for jobs using LinkedIn's public job search"""
        keywords = args.get("keywords", "")
        location = args.get("location", "")
        experience_level = args.get("experience_level", "")
        posted_time = args.get("posted_time", "past_month")
        job_type = args.get("job_type", "")
        remote = args.get("remote", False)
        limit = min(args.get("limit", 25), 100)
        
        # Build LinkedIn job search URL
        params = {
            "keywords": keywords,
            "location": location,
            "f_TPR": self._map_time_filter(posted_time),
            "f_E": self._map_experience_level(experience_level),
            "f_JT": self._map_job_type(job_type),
            "position": 1,
            "pageNum": 0
        }
        
        if remote:
            params["f_WT"] = "2"  # Remote filter
        
        # Remove empty params
        params = {k: v for k, v in params.items() if v}
        
        url = f"https://www.linkedin.com/jobs/search/?{urlencode(params)}"
        
        try:
            response = await self.http_client.get(url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract job listings
            jobs = []
            job_cards = soup.find_all('div', class_='base-card')[:limit]
            
            if not job_cards:
                # Try alternative selectors
                job_cards = soup.find_all('li', class_='jobs-search__results-list')[:limit]
            
            for card in job_cards:
                try:
                    job_data = self._parse_job_card(card)
                    if job_data:
                        jobs.append(job_data)
                except Exception as e:
                    continue
            
            if not jobs:
                return f"No jobs found for '{keywords}'" + (f" in {location}" if location else "") + f"\n\nTry broadening your search or different keywords.\nSearch URL: {url}"
            
            # Format results
            result = f"🔍 Found {len(jobs)} jobs for '{keywords}'"
            if location:
                result += f" in {location}"
            if experience_level:
                result += f" ({experience_level.replace('_', ' ')} level)"
            result += f"\n📅 Posted: {posted_time.replace('_', ' ')}\n"
            result += f"🔗 Full search: {url}\n\n"
            
            for i, job in enumerate(jobs, 1):
                result += f"{i}. 💼 {job['title']}\n"
                result += f"   🏢 {job['company']}\n"
                result += f"   📍 {job['location']}\n"
                if job.get('posted_date'):
                    result += f"   📅 Posted: {job['posted_date']}\n"
                result += f"   🔗 {job['url']}\n\n"
            
            return result
            
        except Exception as e:
            return f"Error searching jobs: {str(e)}\n\nSearch URL attempted: {url}\n\nTip: LinkedIn may be blocking automated requests. Try using different search terms or check the URL manually."
    
    def _parse_job_card(self, card) -> dict:
        """Extract job information from a job card"""
        job = {}
        
        # Try multiple selectors for robustness
        title_elem = card.find('h3', class_='base-search-card__title') or \
                    card.find('a', class_='base-card__full-link')
        
        if title_elem:
            job['title'] = title_elem.get_text(strip=True)
            job['url'] = title_elem.get('href', '') if title_elem.name == 'a' else \
                        card.find('a', class_='base-card__full-link').get('href', '')
        else:
            return None
        
        company_elem = card.find('h4', class_='base-search-card__subtitle') or \
                      card.find('a', class_='hidden-nested-link')
        job['company'] = company_elem.get_text(strip=True) if company_elem else "Company not listed"
        
        location_elem = card.find('span', class_='job-search-card__location')
        job['location'] = location_elem.get_text(strip=True) if location_elem else "Location not specified"
        
        date_elem = card.find('time', class_='job-search-card__listdate')
        job['posted_date'] = date_elem.get_text(strip=True) if date_elem else ""
        
        return job if job.get('title') else None
    
    async def _get_job_details(self, args: dict) -> str:
        """Get detailed job information"""
        job_url_or_id = args.get("job_url_or_id", "")
        
        # Extract job ID if URL provided
        if "linkedin.com" in job_url_or_id:
            job_id = job_url_or_id.split("/view/")[-1].split("?")[0]
        else:
            job_id = job_url_or_id
        
        url = f"https://www.linkedin.com/jobs/view/{job_id}"
        
        try:
            response = await self.http_client.get(url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract job details
            title = soup.find('h1', class_='top-card-layout__title')
            company = soup.find('a', class_='topcard__org-name-link')
            location = soup.find('span', class_='topcard__flavor--bullet')
            description = soup.find('div', class_='show-more-less-html__markup')
            
            result = f"📋 Job Details:\n\n"
            result += f"Title: {title.get_text(strip=True) if title else 'N/A'}\n"
            result += f"Company: {company.get_text(strip=True) if company else 'N/A'}\n"
            result += f"Location: {location.get_text(strip=True) if location else 'N/A'}\n"
            result += f"URL: {url}\n\n"
            
            if description:
                result += f"Description:\n{description.get_text(separator='\n', strip=True)}\n"
            else:
                result += "Description: Not available (may require login)\n"
            
            return result
            
        except Exception as e:
            return f"Error fetching job details: {str(e)}\n\nURL: {url}\n\nNote: Full job descriptions may require LinkedIn login."
    
    async def _search_companies(self, args: dict) -> str:
        """Search for companies"""
        company_name = args.get("company_name", "")
        
        url = f"https://www.linkedin.com/company/{quote_plus(company_name.lower().replace(' ', '-'))}"
        
        try:
            response = await self.http_client.get(url)
            
            if response.status_code == 200:
                return f"✅ Found company: {company_name}\n🔗 {url}\n\nUse 'get_company_jobs' to see their job openings."
            else:
                return f"❌ Company '{company_name}' not found at standard URL.\n\nTry searching manually: https://www.linkedin.com/search/results/companies/?keywords={quote_plus(company_name)}"
                
        except Exception as e:
            return f"Error searching company: {str(e)}"
    
    async def _get_company_jobs(self, args: dict) -> str:
        """Get jobs from a specific company"""
        company_name = args.get("company_name", "")
        limit = min(args.get("limit", 25), 100)
        
        # Search for jobs at the company
        return await self._search_jobs({
            "keywords": f"{company_name}",
            "limit": limit
        })
    
    async def _analyze_job_market(self, args: dict) -> str:
        """Analyze job market trends"""
        role = args.get("role", "")
        location = args.get("location", "")
        
        # Search with high limit to get market data
        jobs_result = await self._search_jobs({
            "keywords": role,
            "location": location,
            "limit": 100,
            "posted_time": "past_month"
        })
        
        # Parse the results to extract insights
        lines = jobs_result.split('\n')
        job_count = 0
        companies = {}
        locations = {}
        
        for line in lines:
            if line.strip().startswith('🏢'):
                company = line.split('🏢')[-1].strip()
                companies[company] = companies.get(company, 0) + 1
                job_count += 1
            elif line.strip().startswith('📍'):
                loc = line.split('📍')[-1].strip()
                locations[loc] = locations.get(loc, 0) + 1
        
        result = f"📊 Job Market Analysis for '{role}'"
        if location:
            result += f" in {location}"
        result += f"\n\n"
        result += f"📈 Total Active Postings: {job_count}\n"
        result += f"📅 Time Period: Past 30 days\n\n"
        
        if companies:
            result += "🏆 Top Hiring Companies:\n"
            for company, count in sorted(companies.items(), key=lambda x: x[1], reverse=True)[:10]:
                result += f"   • {company}: {count} opening(s)\n"
            result += "\n"
        
        if locations:
            result += "🌍 Top Locations:\n"
            for loc, count in sorted(locations.items(), key=lambda x: x[1], reverse=True)[:10]:
                result += f"   • {loc}: {count} opening(s)\n"
        
        return result
    
    def _map_time_filter(self, posted_time: str) -> str:
        """Map time filter to LinkedIn parameter"""
        mapping = {
            "past_24h": "r86400",
            "past_week": "r604800",
            "past_month": "r2592000",
            "any_time": ""
        }
        return mapping.get(posted_time, "r2592000")
    
    def _map_experience_level(self, level: str) -> str:
        """Map experience level to LinkedIn parameter"""
        mapping = {
            "internship": "1",
            "entry_level": "2",
            "associate": "3",
            "mid_senior": "4",
            "director": "5",
            "executive": "6"
        }
        return mapping.get(level, "")
    
    def _map_job_type(self, job_type: str) -> str:
        """Map job type to LinkedIn parameter"""
        mapping = {
            "full_time": "F",
            "part_time": "P",
            "contract": "C",
            "temporary": "T",
            "internship": "I",
            "volunteer": "V"
        }
        return mapping.get(job_type, "")
    
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