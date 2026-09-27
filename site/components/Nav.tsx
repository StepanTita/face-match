export default function Nav() {
  return (
    <nav>
      <div className="logo">
        <span className="logo-mark"></span>facematch
      </div>
      <div className="nav-links">
        <a href="#how">How it works</a>
        <a href="#demo">Demo</a>
        <a href="#get">Buy</a>
      </div>
      <a className="nav-cta" href="#get">
        Buy access
      </a>
    </nav>
  );
}
