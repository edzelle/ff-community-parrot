import { useEffect, useState } from 'react';
import PlayerCard from './PlayerCard';
import './App.css';
import Navbar from './Navbar';

function App() {
  const [players, setPlayers] = useState([]);
  const [search, setSearch] = useState('');
  const [sortAsc, setSortAsc] = useState(false); // default: descending

  useEffect(() => {
    fetch('http://localhost:5000/data')
      .then(res => res.json())
      .then(data => {
        const playerArray = Object.entries(data).map(([name, info]) => ({
          name,
          score: info.sentiment_score,
          texts: info.texts,
        }));
        setPlayers(playerArray);
      });
  }, []);

  const filtered = players
    .filter(p => p.name.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => sortAsc ? a.score - b.score : b.score - a.score);

  return (
    <div className="App">
      <h1>Fantasy Football SquawkScore</h1>

      <div className="search-wrapper">
        <input
          type="text"
          placeholder="Search players..."
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
        {search && (
          <button
            className="clear-btn"
            onClick={() => setSearch('')}
            title="Clear search"
          >
            ×
          </button>
        )}
      </div>

      <button className="sort-btn" onClick={() => setSortAsc(!sortAsc)}>
        Sort by Sentiment {sortAsc ? '↑ (Low → High)' : '↓ (High → Low)'}
      </button>

      <div className="player-list">
        {filtered.map((player, index) => (
          <PlayerCard key={index} player={player} />
        ))}
      </div>
    </div>
  );
}

export default App;
