from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware 
import httpx
from pydantic import BaseModel
from typing import Optional

app = FastAPI(
    title="Travel Condition API",
    description="A RESTful API that intelligently resolves city ambiguity to recommend travel.",
    version="1.1.0",
)
# Add CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://andrewcastro.dev"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- DATA MODELS ---
class Weather(BaseModel):
    temperature_c: float
    condition: str
    wind_speed: float

class Recommendation(BaseModel):
    country: str  
    city: str
    state: Optional[str]
    score: int
    score_verdict: str
    details: Weather

# --- LOGIC ALGORITHM ---
def get_score(temp: float, wind: float, rain: float) -> dict:
    score = 100
    score_verdict = "Perfect"


    # Temperature Logic
    ideal_temp = 25
    diff = abs(temp - ideal_temp) # gradually subtract points based on the difference (sway) from ideal_temp
    score -= (diff * 2.0)
    if temp < -5:
        score_verdict = "Dangerously Cold"
    elif temp < 0:
        score_verdict = "Freezing"
    elif temp < 5:
        score_verdict = "Very Cold"
    elif temp < 10:
        score_verdict = "Cold"
    elif temp < 16:
        score_verdict = "Chilly"
    elif temp < 26:
        score_verdict = "Perfect"
    elif temp < 30:
        score_verdict = "Warm"
    elif temp < 35:
        score_verdict = "Hot"
    elif temp < 40:
        score_verdict = "Very Hot"
    else:
        score_verdict = "Dangerously Hot"

    
    # Wind Logic
    ideal_wind = 0
    diff = abs(wind - ideal_wind) # gradually subtract points based on the difference (sway) from ideal_wind
    score -= (diff * 0.5)
    if wind < 5:
        score_verdict += " & Calm Winds"
    elif wind < 12:
        score_verdict += " & Light Breeze"
    elif wind < 20:
        score_verdict += " & Breezy"
    elif wind < 30:
        score_verdict += " & Windy"
    elif wind < 50:
        score_verdict += " & Strong Winds"
    elif wind < 75:
        score_verdict += " & Gale Force"
    else:
        score_verdict += " & Violent Storm"
        
    # Rain Logic
    ideal_rain = 0 
    diff = abs(rain - ideal_rain) # gradually subtract points based on the difference (sway) from ideal_rain
    score -= (diff * 4.0)
    if rain == 0:
        score_verdict += " & Dry Conditions"
    elif rain < 0.5:    
        score_verdict += " & Drizzling"
    elif rain < 2.5:
        score_verdict += " & Light Rain"
    elif rain < 7.6:
        score_verdict += " & Moderate Rain"
    elif rain < 10:
        score_verdict += " & Heavy Rain" 
    elif rain < 50:
        score_verdict += " & Potential Floods"
    else:
        score_verdict += " & Torrential/Flash Flooding"  

    return {"score": max(0, score), "score_verdict": score_verdict}

# --- ENDPOINT ---
@app.get("/recommend-trip", response_model=Recommendation)
async def recommend_trip(
    country_code: str = Query(..., min_length=2, max_length=2, description="ISO Country code (e.g. US, GB, CA)"),
    city: str = Query(..., description="City name (e.g. Warwick)"),
    state: Optional[str] = Query(None, description="State (e.g. Rhode Island, New York)"),
):
    async with httpx.AsyncClient() as client:

        # Mateo requires lat/long so we use geocoding to map it
        # FETCH first 10 results
        geo_url = "https://geocoding-api.open-meteo.com/v1/search"
        geo_params = {
            "name": city, 
            "count": 10,  
            "language": "en", 
            "format": "json"
        }

        try:
            geo_resp = await client.get(geo_url, params=geo_params)
            geo_resp.raise_for_status()
            geo_data = geo_resp.json()
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="Geocoding API is down")

        if not geo_data.get("results"):
            raise HTTPException(status_code=404, detail="City could not be found")

        # Get the best match from the fetch list
        selected_location = None
        candidates = geo_data["results"]

        for candidate in candidates:
            if country_code and candidate.get("country_code", "").upper() != country_code.upper():
                continue

            # If user provided state, skip if it doesn't match
            # Meteo stores states in "admin1"
            if state:
                admin1 = candidate.get("admin1", "").lower()
                if state.lower() not in admin1: 
                    continue

            # If we passed the checks (or no checks were needed), we found our city
            selected_location = candidate
            break # Stop the looping

        # If we filtered everything out and found nothing:
        if not selected_location:
             raise HTTPException(status_code=404, detail=f"Could not find {city} in {state or 'any state'}, {country_code or 'any country'}")

        # Extract location data from the searched location
        lat = selected_location["latitude"]
        lon = selected_location["longitude"]
        resolved_country = selected_location.get("country", "Unknown")
        resolved_state = selected_location.get("admin1", "Unknown") 
        resolved_name = selected_location["name"]

        #-- Fetches weather conditions
        weather_url = "https://api.open-meteo.com/v1/forecast"
        weather_params = {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,rain,wind_speed_10m",
        }

        try:
            weather_resp = await client.get(weather_url, params=weather_params)
            weather_resp.raise_for_status()
            weather_data = weather_resp.json()
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="Weather service unavailable")

    # Extract data
    current = weather_data.get("current", {})
    temp = current.get("temperature_2m", 0)
    rain = current.get("rain", 0)
    wind = current.get("wind_speed_10m", 0)

    # Run Algorithm
    analysis = get_score(temp, wind, rain)

    return {
        "city": resolved_name,
        "state": resolved_state,
        "country": resolved_country,
        "score": analysis["score"],
        "score_verdict": analysis["score_verdict"],
        "details": {
            "temperature_c": temp,
            "condition": "Raining" if rain > 0 else "Clear",
            "wind_speed": wind,
        },
    }