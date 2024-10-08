from enum import Enum
from dataclasses import dataclass
import sqlite3
from fastapi import FastAPI
from fastapi.responses import JSONResponse, FileResponse
from fastapi.requests import Request
import uvicorn

class MatchResult(Enum):
    A_WIN = 1
    B_WIN = 2
    DRAW = 3

class FourWayMatchResult(Enum):
    A_WIN = 0
    B_WIN = 1
    C_WIN = 2
    D_WIN = 3
    DRAW = 4


def calculate_elos(player_a_rating: int, player_b_rating, result: MatchResult) -> tuple[int, int]:
    # Calculate the expected score for each player
    expected_a = 1 / (1 + 10 ** ((player_b_rating - player_a_rating) / 400))
    expected_b = 1 - expected_a

    # Calculate the actual score for each player
    if result == MatchResult.A_WIN:
        actual_a = 1
        actual_b = 0
    elif result == MatchResult.B_WIN:
        actual_a = 0
        actual_b = 1
    else:
        actual_a = 0.5
        actual_b = 0.5

    # Calculate the new ratings for each player
    new_a_rating = player_a_rating + 32 * (actual_a - expected_a)
    new_b_rating = player_b_rating + 32 * (actual_b - expected_b)

    new_a_rating = int(new_a_rating)
    new_b_rating = int(new_b_rating)

    return new_a_rating, new_b_rating

def four_way_elo(player_a_rating: int, player_b_rating: int, player_c_rating: int, player_d_rating: int, winner_idx: int) -> tuple[int, int, int, int]:

    assert winner_idx in [0, 1, 2, 3]

    ratings = [player_a_rating, player_b_rating, player_c_rating, player_d_rating]

    winner_rating = ratings.pop(winner_idx)

    new_ratings = [calculate_elos(rating, winner_rating, MatchResult.B_WIN) for rating in ratings]

    winner_elo_gained = sum([new_rating - winner_rating for _, new_rating in new_ratings])

    new_ratings.insert(winner_idx, (winner_rating + winner_elo_gained, 0))

    return tuple([rating for rating, _ in new_ratings])
    

@dataclass
class MtgDeck:
    name: str
    commander: list[str]
    decklist: list[str]
    elo_rating: int
    owner: str

    def update_rating(self, new_rating: int):
        self.elo_rating = new_rating


@dataclass
class MtgMatch:
    players: list[str]
    decks: list[MtgDeck]
    result: FourWayMatchResult



class DB:
    path: str
    conn: sqlite3.Connection
    cursor: sqlite3.Cursor

    def __init__(self, path: str):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.cursor = self.conn.cursor()

    def create_tables(self):
        decks_cmd = """
        CREATE TABLE if not exists decks (
            name TEXT PRIMARY KEY UNIQUE,
            commander TEXT,
            decklist TEXT,
            elo_rating INTEGER,
            owner TEXT
        );
        """

        matches_cmd = """
        CREATE TABLE if not exists matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            players TEXT,
            decks TEXT,
            result INTEGER
        );
        """
    
        self.cursor.execute(decks_cmd)
        self.cursor.execute(matches_cmd)
        self.conn.commit()
    
    def add_or_update_deck(self, deck: MtgDeck):
        cmd = """
        INSERT OR REPLACE INTO decks (name, commander, decklist, elo_rating, owner)
        VALUES (?, ?, ?, ?, ?);
        """

        self.cursor.execute(cmd, (deck.name, ";".join(deck.commander), ";".join(deck.decklist), deck.elo_rating, deck.owner))
        self.conn.commit()
    
    def add_match(self, match: MtgMatch):
        cmd = """
        INSERT INTO matches (players, decks, result)
        VALUES (?, ?, ?);
        """

        self.cursor.execute(cmd, (";".join(match.players), ";".join([deck.name for deck in match.decks]), match.result.value))
        self.conn.commit()
    
    def get_deck(self, name: str) -> MtgDeck:
        cmd = """
        SELECT * FROM decks WHERE name = ?;
        """

        self.cursor.execute(cmd, (name,))
        result = self.cursor.fetchone()

        if result is None:
            return None

        result = list(result)
        result[1] = result[1].split(";")
        result[2] = result[2].split(";")

        return MtgDeck(*result)
    
    def get_all_decks(self) -> list[MtgDeck]:
        cmd = """
        SELECT * FROM decks;
        """

        self.cursor.execute(cmd)
        results = self.cursor.fetchall()

        decks_out = []
        for result in results:
            result = list(result)
            result[1] = result[1].split(";")
            result[2] = result[2].split(";")
            decks_out.append(MtgDeck(*result))
        
        return decks_out
    
    def get_all_matches(self) -> list[MtgMatch]:
        cmd = """
        SELECT * FROM matches;
        """

        self.cursor.execute(cmd)
        results = self.cursor.fetchall()

        matches_out = []

        for result in results:
            result = list(result)
            result[1] = result[1].split(";")
            result[2] = [self.get_deck(deck_name) for deck_name in result[2].split(";")]
            result[3] = FourWayMatchResult(result[3])
            matches_out.append(MtgMatch(*result))


    def close(self):
        self.conn.close()



app = FastAPI()
db = DB("./data/mtg_decks.db")
db.create_tables()

@app.get("/")
async def root():
    return FileResponse("./sites/index.html")

@app.get("/styles.css")
async def styles():
    return FileResponse("./sites/styles.css")

@app.get("/index.html")
async def index_site():
    return FileResponse("./sites/index.html")

@app.get("/add_deck.html")
async def add_deck_site():
    return FileResponse("./sites/add_deck.html")

@app.get("/live_match.html")
async def live_match_site():
    return FileResponse("./sites/live_match.html")

@app.post("/add_deck")
async def add_deck(deck: MtgDeck):
    db.add_or_update_deck(deck)
    return JSONResponse(content={"message": "Deck added successfully.", "success": True})



@app.get("/get_deck")
async def get_deck(name: str):
    deck = db.get_deck(name)

    if deck is None:
        return JSONResponse(content={"message": "Deck not found.", "success": False})
    
    return JSONResponse(content=deck.__dict__)

@app.get("/get_all_decks")
async def get_all_decks():
    decks = db.get_all_decks()
    return JSONResponse(content=[deck.__dict__ for deck in decks])

@app.get("/get_all_decks_names")
async def get_all_decks_names():
    decks = db.get_all_decks()
    deck_names = []
    for deck in decks:
        deck_name = deck.name + " - " + deck.commander[0] + " (" + deck.owner + ")"
        deck_names.append(deck_name)
    
    return JSONResponse(content=deck_names)


@app.post("/add_match")
async def add_match(match: MtgMatch):
    db.add_match(match)

    decks = match.decks
    winner_idx = match.result.value
    new_ratings = four_way_elo(decks[0].elo_rating, decks[1].elo_rating, decks[2].elo_rating, decks[3].elo_rating, winner_idx)
    for i, deck in enumerate(decks):
        deck.update_rating(new_ratings[i])
        db.add_or_update_deck(deck)

    return JSONResponse(content={"message": "Match added successfully.", "success": True})

@app.get("/get_all_matches")
async def get_all_matches():
    matches = db.get_all_matches()
    return JSONResponse(content=[match.__dict__ for match in matches])


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)