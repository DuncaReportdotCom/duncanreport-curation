#!/usr/bin/env python3
"""
DuncanReport.com - self-contained site builder (v1).

Reads index.html from the repo root and writes a ready-to-publish ./site folder with a
stories.json for every section (plus the routing file). The first-stab section data is
embedded below, so the ONLY file you need in the repo besides this one is index.html.
The main page pulls its current data from the live site. The workflow runs this, then
Wrangler publishes ./site. Live AI curation can be layered on later.
"""
import os, json, shutil, time, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(ROOT, "site")

SEEDS = json.loads(r"""
{
 "sports": {
  "lastUpdated": 1784908800000,
  "scoreboard": [
   {
    "league": "MLB",
    "away": "Colorado Rockies",
    "home": "Milwaukee Brewers",
    "awayScore": null,
    "homeScore": null,
    "state": "scheduled",
    "note": "4:10 PM ET",
    "url": "https://www.espn.com/mlb/scoreboard"
   },
   {
    "league": "MLB",
    "away": "Kansas City Royals",
    "home": "Detroit Tigers",
    "awayScore": null,
    "homeScore": null,
    "state": "scheduled",
    "note": "6:40 PM ET",
    "url": "https://www.espn.com/mlb/scoreboard"
   },
   {
    "league": "MLB",
    "away": "Chicago Cubs",
    "home": "Pittsburgh Pirates",
    "awayScore": null,
    "homeScore": null,
    "state": "scheduled",
    "note": "6:40 PM ET",
    "url": "https://www.espn.com/mlb/scoreboard"
   },
   {
    "league": "MLB",
    "away": "Arizona Diamondbacks",
    "home": "Washington Nationals",
    "awayScore": null,
    "homeScore": null,
    "state": "scheduled",
    "note": "6:45 PM ET",
    "url": "https://www.espn.com/mlb/scoreboard"
   },
   {
    "league": "MLB",
    "away": "New York Yankees",
    "home": "Philadelphia Phillies",
    "awayScore": null,
    "homeScore": null,
    "state": "scheduled",
    "note": "6:45 PM ET",
    "url": "https://www.espn.com/mlb/scoreboard"
   },
   {
    "league": "MLB",
    "away": "Atlanta Braves",
    "home": "Baltimore Orioles",
    "awayScore": null,
    "homeScore": null,
    "state": "scheduled",
    "note": "7:05 PM ET",
    "url": "https://www.espn.com/mlb/scoreboard"
   },
   {
    "league": "MLB",
    "away": "Los Angeles Dodgers",
    "home": "New York Mets",
    "awayScore": null,
    "homeScore": null,
    "state": "scheduled",
    "note": "7:10 PM ET",
    "url": "https://www.espn.com/mlb/scoreboard"
   },
   {
    "league": "MLB",
    "away": "Cleveland Guardians",
    "home": "Tampa Bay Rays",
    "awayScore": null,
    "homeScore": null,
    "state": "scheduled",
    "note": "7:10 PM ET",
    "url": "https://www.espn.com/mlb/scoreboard"
   },
   {
    "league": "MLB",
    "away": "San Diego Padres",
    "home": "Miami Marlins",
    "awayScore": null,
    "homeScore": null,
    "state": "scheduled",
    "note": "7:10 PM ET",
    "url": "https://www.espn.com/mlb/scoreboard"
   },
   {
    "league": "MLB",
    "away": "Toronto Blue Jays",
    "home": "Boston Red Sox",
    "awayScore": null,
    "homeScore": null,
    "state": "scheduled",
    "note": "7:15 PM ET",
    "url": "https://www.espn.com/mlb/scoreboard"
   },
   {
    "league": "MLB",
    "away": "Houston Astros",
    "home": "Chicago White Sox",
    "awayScore": null,
    "homeScore": null,
    "state": "scheduled",
    "note": "7:40 PM ET",
    "url": "https://www.espn.com/mlb/scoreboard"
   },
   {
    "league": "MLB",
    "away": "Seattle Mariners",
    "home": "Texas Rangers",
    "awayScore": null,
    "homeScore": null,
    "state": "scheduled",
    "note": "8:05 PM ET",
    "url": "https://www.espn.com/mlb/scoreboard"
   },
   {
    "league": "MLB",
    "away": "Oakland Athletics",
    "home": "Minnesota Twins",
    "awayScore": null,
    "homeScore": null,
    "state": "scheduled",
    "note": "8:10 PM ET",
    "url": "https://www.espn.com/mlb/scoreboard"
   },
   {
    "league": "MLB",
    "away": "Cincinnati Reds",
    "home": "St. Louis Cardinals",
    "awayScore": null,
    "homeScore": null,
    "state": "scheduled",
    "note": "8:15 PM ET",
    "url": "https://www.espn.com/mlb/scoreboard"
   },
   {
    "league": "MLB",
    "away": "Los Angeles Angels",
    "home": "San Francisco Giants",
    "awayScore": null,
    "homeScore": null,
    "state": "scheduled",
    "note": "10:15 PM ET",
    "url": "https://www.espn.com/mlb/scoreboard"
   },
   {
    "league": "WNBA",
    "away": "All-Star 3-Point Contest",
    "home": "Shooting Stars",
    "awayScore": null,
    "homeScore": null,
    "state": "scheduled",
    "note": "8:00 PM ET · Chicago",
    "url": "https://www.espn.com/wnba/scoreboard"
   }
  ],
  "hero": {
   "headline": "WNBA ALL-STAR WEEKEND TIPS OFF IN CHICAGO WITH 3-POINT CONTEST AND SHOOTING STARS",
   "url": "https://ticket760.iheart.com/content/2026-07-24-wnba-all-star-weekend-kicks-off-in-chicago/",
   "sublinks": [
    {
     "text": "Fudd, Mabrey, Howard in 3-point field",
     "url": "https://www.espn.com/wnba/story/_/id/49420142/fudd-mabrey-howard-wnba-all-star-3-point-contestants"
    },
    {
     "text": "How to watch tonight",
     "url": "https://www.nbcchicago.com/wnba/all-star-3-point-contest-shooting-stars-date-time-channel-stream/3965115/"
    },
    {
     "text": "Clark, Ionescu skip 3-point contest",
     "url": "https://frontofficesports.com/sabrina-ionescu-caitlin-clark-skipping-wnba-3-point-contest/"
    }
   ]
  },
  "groups": [
   {
    "title": "MLB TRADE DEADLINE HEATS UP",
    "stories": [
     {
      "headline": "Trade Deadline Tracker: Skubal, Mets Arms, Mason Miller Buzz",
      "url": "https://www.espn.com/mlb/story/_/id/49410877/2026-mlb-trade-deadline-tracker-rumors-alerts-news-latest-updates-analysis",
      "timestamp": 1784894400000
     },
     {
      "headline": "Rumors: Hunter Greene, Phillies, Yankees, Mariners, Red Sox",
      "url": "https://www.cbssports.com/mlb/news/mlb-rumors-trade-deadline-phillies-rotation-yankees/",
      "timestamp": 1784829600000
     }
    ]
   }
  ],
  "columns": {
   "left": [
    {
     "headline": "Panthers DE Nic Scourton Tears ACL in First Camp Practice",
     "url": "https://www.nfl.com/news/nfl-news-roundup-latest-league-updates-from-thursday-july-23",
     "timestamp": 1784833200000
    }
   ],
   "center": [
    {
     "headline": "Raiders, No. 1 Pick Fernando Mendoza Agree to Rookie Deal",
     "url": "https://ca.sports.yahoo.com/news/nfl-news-live-updates-training-camp-2026-schedule-injury-news-163112222.html",
     "timestamp": 1784826000000
    }
   ],
   "right": [
    {
     "headline": "NBA Offseason Tracker: Jaylen Brown Buzz, Summer League Intel",
     "url": "https://sports.yahoo.com/nba/article/2026-nba-offseason-trade-tracker-deal-details-analysis-220745003.html",
     "timestamp": 1784844000000
    }
   ]
  }
 },
 "world": {
  "lastUpdated": 1784908800000,
  "hero": {
   "headline": "U.S. STRIKES IRAN FOR 13TH STRAIGHT NIGHT AS TEHRAN REJECTS CEASEFIRE; OIL TOPS $100",
   "url": "https://www.cnn.com/2026/07/23/world/live-news/iran-war-trump",
   "sublinks": [
    {
     "text": "Oil tops $100 after Houthi Red Sea attacks",
     "url": "https://www.bloomberg.com/news/articles/2026-07-23/how-houthis-red-sea-attacks-worsen-oil-shock"
    },
    {
     "text": "Mediators push 10-day ceasefire",
     "url": "https://www.cnbc.com/2026/07/21/us-iran-war-trump-hormuz-houthis.html"
    },
    {
     "text": "Background: the 2026 Iran War",
     "url": "https://www.britannica.com/event/2026-Iran-war"
    }
   ]
  },
  "groups": [
   {
    "title": "RED SEA OIL SHOCK",
    "stories": [
     {
      "headline": "Saudi Oil Tanker Attacked in Red Sea as War Risks Widen",
      "url": "https://www.washingtonpost.com/world/2026/07/23/least-one-saudi-oil-tanker-is-attacked-red-sea-war-risks-widen/",
      "timestamp": 1784804400000
     },
     {
      "headline": "Experts Watch Red Sea Tankers for Clarity on Houthi Blockade",
      "url": "https://www.aljazeera.com/economy/2026/7/24/as-oil-soars-experts-watch-red-sea-tankers-for-clarity-on-houthi-blockade",
      "timestamp": 1784883600000
     }
    ]
   }
  ],
  "columns": {
   "left": [
    {
     "headline": "Some 40,000 Evacuated as Wildfire Rages in Southwest France",
     "url": "https://www.france24.com/en/live-news/20260724-some-40-000-people-evacuated-due-to-wildfire-in-southwest-france-minister",
     "timestamp": 1784887200000
    },
    {
     "headline": "Trump's Latest Tariffs Blasted by EU, Brazil and Australia",
     "url": "https://www.forbes.com/sites/siladityaray/2026/07/24/unjustified-eu-brazil-and-others-criticize-latest-trump-tariffs/",
     "timestamp": 1784894400000
    }
   ],
   "center": [
    {
     "headline": "At Least 21 Killed as Ukraine and Russia Trade Attacks",
     "url": "https://www.aljazeera.com/news/2026/7/24/at-least-11-killed-in-ukraine-as-moscow-and-kyiv-continue-to-trade-attacks",
     "timestamp": 1784880000000
    }
   ],
   "right": [
    {
     "headline": "Indian Activist Wangchuk Ends 26-Day Hunger Strike",
     "url": "https://www.usnews.com/news/world/articles/2026-07-23/indian-activist-wangchuk-ends-26-day-hunger-strike",
     "timestamp": 1784811600000
    },
    {
     "headline": "Mexican Mayor Shot Dead in Town Hall After Surviving Earlier Attempt",
     "url": "https://www.bloomberg.com/news/articles/2026-07-23/mexican-mayor-shot-dead-in-his-office-after-surviving-earlier-hit",
     "timestamp": 1784772000000
    }
   ]
  }
 },
 "markets": {
  "lastUpdated": 1784908800000,
  "markets": [
   {
    "name": "S&P 500",
    "value": "7,408.30",
    "change": "-90.66",
    "changePct": "-1.2%"
   },
   {
    "name": "Dow Jones",
    "value": "51,711.65",
    "change": "-506.93",
    "changePct": "-1.0%"
   },
   {
    "name": "Nasdaq",
    "value": "25,137.69",
    "change": "-553.21",
    "changePct": "-2.2%"
   },
   {
    "name": "10-Yr Treasury",
    "value": "4.71%",
    "change": "+0.06",
    "changePct": ""
   },
   {
    "name": "Gold",
    "value": "$4,055.82",
    "change": "",
    "changePct": ""
   },
   {
    "name": "Bitcoin",
    "value": "$64,304.50",
    "change": "-1,046",
    "changePct": "-1.6%"
   },
   {
    "name": "Brent Crude",
    "value": "$100.69",
    "change": "+6.60",
    "changePct": "+7.0%"
   }
  ],
  "hero": {
   "headline": "TRUMP HITS 60 ECONOMIES WITH NEW 10%-12.5% TARIFFS AS BLANKET LEVIES EXPIRE",
   "url": "https://www.bloomberg.com/news/articles/2026-07-24/here-s-the-full-list-of-trump-s-new-tariffs-on-60-economies",
   "sublinks": [
    {
     "text": "CNN: tariffs target dozens of countries",
     "url": "https://www.cnn.com/2026/07/23/economy/trump-new-tariffs"
    },
    {
     "text": "NBC: new 10%-12.5% rates on 60 partners",
     "url": "https://www.nbcnews.com/business/economy/trump-tariffs-60-countries-forced-labor-rcna588972"
    },
    {
     "text": "What investors should watch",
     "url": "https://www.chase.com/personal/investments/learning-and-insights/article/trump-tariffs-key-considerations-for-investors-before-july-24-2026"
    }
   ]
  },
  "groups": [
   {
    "title": "MARKETS SELL OFF ON AI SPENDING AND OIL",
    "stories": [
     {
      "headline": "Dow Drops 500 Points as Brent Surges Above $100",
      "url": "https://www.cnbc.com/2026/07/22/stock-market-today-live-updates.html",
      "timestamp": 1784750400000
     },
     {
      "headline": "Alphabet Q2 Beats but Stock Sinks on $200B Capex Hike",
      "url": "https://www.cnbc.com/2026/07/22/google-earnings-q2-goog-live-updates.html",
      "timestamp": 1784754000000
     },
     {
      "headline": "Tesla Q2 Revenue Beats, Profit Misses; Stock Tumbles 14.5%",
      "url": "https://electrek.co/2026/07/22/tesla-tsla-q2-2026-financial-results/",
      "timestamp": 1784755800000
     }
    ]
   }
  ],
  "columns": {
   "left": [
    {
     "headline": "Brent Crude Crosses $100 After Tankers Struck Off Saudi Arabia",
     "url": "https://www.cnbc.com/2026/07/23/oil-prices-today-wti-brent-trump-iran-hormuz.html",
     "timestamp": 1784808000000
    },
    {
     "headline": "Intel Q2 Beats: Revenue Up 25% to $16.1B; Shares Jump 12%",
     "url": "https://www.tradingkey.com/analysis/stocks/us-stocks/262050823-intel-earnings-report-q2-2026-intc-ai-data-center-intel-foundry-tradingkey",
     "timestamp": 1784844000000
    }
   ],
   "center": [
    {
     "headline": "Wall Street Rebounds Friday as Oil Falls on U.S.-Iran Talk Hopes",
     "url": "https://finance.yahoo.com/markets/live/stock-market-today-friday-july-24-dow-sp-500-nasdaq-081854465.html",
     "timestamp": 1784898000000
    },
    {
     "headline": "10-Year Treasury Yield Climbs to 4.71%, Highest Since January 2025",
     "url": "https://finance.yahoo.com/personal-finance/investing/article/bitcoin-and-ethereum-prices-today-friday-july-24-2026-crypto-prices-retreat-on-higher-us-treasury-yields-152200068.html",
     "timestamp": 1784836800000
    }
   ],
   "right": [
    {
     "headline": "Fed's Warsh Turns Hawkish; Rate-Hike Odds Rise Before July 29",
     "url": "https://www.forbes.com/sites/investor-hub/article/fed-meeting-tracker-interest-rate-strategy/",
     "timestamp": 1784822400000
    }
   ]
  }
 },
 "politics": {
  "lastUpdated": 1784908800000,
  "hero": {
   "headline": "IRAN REJECTS U.S. CEASEFIRE AS AMERICAN STRIKES HIT 13TH STRAIGHT NIGHT",
   "url": "https://www.cnn.com/2026/07/23/world/live-news/iran-war-trump",
   "sublinks": [
    {
     "text": "House votes 214-208 to halt the war",
     "url": "https://rollcall.com/2026/07/23/23warpowersvote/"
    },
    {
     "text": "Oil tops $100 as war squeezes supply",
     "url": "https://www.cnn.com/2026/07/24/business/oil-prices-inflation-bonds-iran-war"
    },
    {
     "text": "Tehran rejects reported truce",
     "url": "https://www.haaretz.com/middle-east-news/iran/2026-07-24/ty-article/iran-rejects-reported-trump-truce-as-u-s-completes-13th-night-of-strikes/0000019f-936e-d1a3-adff-f3ff9a1d0000"
    }
   ]
  },
  "groups": [
   {
    "title": "THE IRAN WAR ON CAPITOL HILL",
    "stories": [
     {
      "headline": "House Again Votes to Halt Trump's Iran War in 214-208 Rebuke",
      "url": "https://www.bloomberg.com/news/articles/2026-07-23/us-house-rebukes-trump-on-iran-votes-again-to-end-war",
      "timestamp": 1784840400000
     },
     {
      "headline": "Fallen U.S. Troops Return to Dover in Flag-Draped Caskets",
      "url": "https://www.militarytimes.com/news/your-military/2026/07/22/4-us-soldiers-killed-in-iran-war-return-to-american-soil/",
      "timestamp": 1784743200000
     },
     {
      "headline": "Trump Says Saudi Nuclear Deal Now Hinges on Abraham Accords",
      "url": "https://www.cnn.com/2026/07/23/politics/saudi-arabia-nuclear-deal-trump",
      "timestamp": 1784815200000
     }
    ]
   }
  ],
  "columns": {
   "left": [
    {
     "headline": "DOJ Drops Subpoenas of New York Times Reporters After Judge's Rebuke",
     "url": "https://www.cnn.com/2026/07/23/media/new-york-times-subpoenas-trump-doj-prosecutors",
     "timestamp": 1784820600000
    },
    {
     "headline": "NYC Landlords Sue to Overturn Mamdani-Backed Rent Freeze",
     "url": "https://www.bloomberg.com/news/articles/2026-07-22/nyc-landlords-sue-to-invalidate-mamdani-backed-rent-freeze",
     "timestamp": 1784725200000
    }
   ],
   "center": [
    {
     "headline": "Man Who Killed Minnesota Lawmaker Melissa Hortman Gets Two Life Sentences",
     "url": "https://www.cnn.com/2026/07/23/us/mn-lawmakers-killing-sentencing",
     "timestamp": 1784826000000
    }
   ],
   "right": [
    {
     "headline": "Trump Cites Anti-Slavery Trade Law to Hit 60 Trading Partners With Tariffs",
     "url": "https://www.npr.org/2026/07/24/nx-s1-5906301/us-global-trump-tariffs-reaction",
     "timestamp": 1784890800000
    },
    {
     "headline": "Fox Power Rankings: GOP Redistricting Offsets Democrats' 2026 Edge",
     "url": "https://www.foxnews.com/politics/fox-news-power-rankings-democrats-lead-house-redistricting-keeps-gop-game",
     "timestamp": 1784736000000
    }
   ]
  }
 },
 "life-culture": {
  "lastUpdated": 1784908800000,
  "hero": {
   "headline": "SAN DIEGO COMIC-CON 2026 TAKES OVER — POP CULTURE'S BIGGEST WEEKEND IS UNDERWAY",
   "url": "https://www.kpbs.org/news/arts-culture/2026/07/23/comic-con-2026-marvel-returns-hall-h-spaceballs-sequel-hype-begins",
   "sublinks": [
    {
     "text": "Johnny Depp surprises as Ebenezer Scrooge",
     "url": "https://variety.com/2026/film/news/johnny-depp-comic-con-surprise-ebenezer-scrooge-1236819764/"
    },
    {
     "text": "Marvel returns to Hall H",
     "url": "https://www.nbclosangeles.com/news/local/comic-con-2026-marvel-returns-to-hall-h-and-spaceballs-sequel-hype-begins/3921035/"
    },
    {
     "text": "All the Marvel news recap",
     "url": "https://www.marvel.com/articles/live-events/sdcc-2026-san-diego-comic-con-all-the-marvel-news-recap"
    }
   ]
  },
  "groups": [
   {
    "title": "COMIC-CON HEADLINES",
    "stories": [
     {
      "headline": "Johnny Depp Debuts 'Ebenezer' Trailer in Hall H Surprise",
      "url": "https://variety.com/2026/film/news/johnny-depp-comic-con-surprise-ebenezer-scrooge-1236819764/",
      "timestamp": 1784847600000
     },
     {
      "headline": "Marvel Builds 'Avengers: Doomsday' Hype Before Saturday Panel",
      "url": "https://www.nbclosangeles.com/news/local/comic-con-2026-marvel-returns-to-hall-h-and-spaceballs-sequel-hype-begins/3921035/",
      "timestamp": 1784836800000
     }
    ]
   }
  ],
  "columns": {
   "left": [
    {
     "headline": "Sean 'Diddy' Combs in Solitary After Prison Fight at Fort Dix",
     "url": "https://www.nbcnews.com/news/us-news/sean-diddy-combs-solitary-confinement-fight-new-jersey-federal-prison-rcna589047",
     "timestamp": 1784898000000
    },
    {
     "headline": "'The Odyssey' Eyes Record Second Weekend for Nolan",
     "url": "https://deadline.com/2026/07/box-office-the-odyssey-tuesday-second-weekend-1236999819/",
     "timestamp": 1784818800000
    }
   ],
   "center": [
    {
     "headline": "Charli XCX Releases 'Music, Fashion, Film' to Critical Acclaim",
     "url": "http://www.thefader.com/2026/07/24/charli-xcx-music-fashion-film-album-review",
     "timestamp": 1784887200000
    }
   ],
   "right": [
    {
     "headline": "Scientists Build a Tiny 'Diving Suit' for Cyborg Cockroaches",
     "url": "https://www.popsci.com/technology/cockroach-diving-suit/",
     "timestamp": 1784815200000
    },
    {
     "headline": "News of the Weird, Week of July 23",
     "url": "https://shepherdexpress.com/puzzles/news-of-the-weird/news-of-the-weird-week-of-july-23-2026/",
     "timestamp": 1784797200000
    }
   ]
  }
 }
}
""")

def main_seed():
    try:
        with urllib.request.urlopen("https://duncanreport.com/stories.json", timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return {"lastUpdated": int(time.time()*1000), "hero": {}, "groups": [],
                "columns": {"left": [], "center": [], "right": []}}

def build():
    if os.path.exists(SITE):
        shutil.rmtree(SITE)
    os.makedirs(SITE)
    src = os.path.join(ROOT, "index.html")
    if not os.path.isfile(src):
        raise SystemExit("ERROR: index.html is missing from the repo root.")
    shutil.copy2(src, os.path.join(SITE, "index.html"))
    fav = os.path.join(ROOT, "favicon.ico")
    if os.path.isfile(fav):
        shutil.copy2(fav, os.path.join(SITE, "favicon.ico"))
    with open(os.path.join(SITE, "_redirects"), "w", encoding="utf-8") as f:
        f.write("/*    /index.html   200\n")
    with open(os.path.join(SITE, "stories.json"), "w", encoding="utf-8") as f:
        json.dump(main_seed(), f, ensure_ascii=False, indent=2)
    for sec, data in SEEDS.items():
        d = os.path.join(SITE, sec); os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "stories.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print("wrote", sec)
    print("Site ready at ./site")

if __name__ == "__main__":
    build()
