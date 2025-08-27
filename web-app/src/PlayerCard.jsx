import { useState } from 'react';
import './PlayerCard.css';

const PlayerCard = ({ player }) => {
  const [expanded, setExpanded] = useState(false);

  // Color scale: red (-1) to green (1)
  const getColor = (score) => {
    const percent = (score + 1) / 2; // scale -1 to 1 → 0 to 1
    const r = Math.round(255 * (1 - percent));
    const g = Math.round(255 * percent);
    return `rgb(${r}, ${g}, 0)`;
  };

  return (
    <div
      className="player-card"
      onClick={() => setExpanded(!expanded)}
      style={{ borderColor: getColor(player.score) }}
    >
      <div className="player-header">
        <span className="player-name">{player.name}</span>
        <span className="player-score" style={{ color: getColor(player.score) }}>
          {player.score.toFixed(2)}
        </span>
      </div>

      {expanded && (
        <ul className="comment-list">
          {player.texts.map((text, i) => (
            <li key={i} className="comment">{text}</li>
          ))}
        </ul>
      )}
    </div>
  );
};

export default PlayerCard;
