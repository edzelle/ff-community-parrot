import React from "react";
import logo from "./assets/SquawkScore_orange_logo.png";

export default function Navbar() {
  return (
    <nav className="navbar">
      {/* Left side: Logo + App name */}
      <div className="navbar-left">
        <img 
          src={logo} 
          alt="SquawkScore logo" 
          className="navbar-logo" 
        />
        <span className="navbar-title">SquawkScore</span>
      </div>

      {/* Right side: Nav links / actions */}
      <div className="navbar-right">
        <a href="#players" className="navbar-link">Players</a>
        <a href="#rankings" className="navbar-link">Rankings</a>
        <a href="#about" className="navbar-link">About</a>
        <button className="navbar-button">Sign In</button>
      </div>
    </nav>
  );
}
