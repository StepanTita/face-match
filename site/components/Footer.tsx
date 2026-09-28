const PHOTO_CREDITS: { name: string; credit: string; license: string; href: string }[] = [
  { name: "Chris Evans (WonderCon 2010)", credit: "BrokenSphere / derivative: Minerva97", license: "CC BY-SA 3.0", href: "https://commons.wikimedia.org/wiki/File%3AChris_Evans_-_The_Losers_film_panel_-_WonderCon_2010.jpg" },
  { name: "Chris Evans", credit: "Gage Skidmore", license: "CC BY-SA 3.0", href: "https://commons.wikimedia.org/wiki/File%3AChris_Evans_by_Gage_Skidmore.jpg" },
  { name: "Chris Evans (2016)", credit: "Chairman of the Joint Chiefs of Staff", license: "CC BY 2.0", href: "https://commons.wikimedia.org/wiki/File%3AChris_Evans_in_Dec_6%2C_2016.jpg" },
  { name: "Chris Evans (2019)", credit: "US House of Representatives — Office of Don Young", license: "Public domain", href: "https://commons.wikimedia.org/wiki/File%3AChris_Evans_in_2019.jpg" },
  { name: "Chris Evans (2020)", credit: "Tony Cárdenas", license: "Public domain", href: "https://commons.wikimedia.org/wiki/File%3AChris_Evans_2020_%28cropped%29.jpg" },
  { name: "Chris Evans (2025)", credit: "Sara Komatsu", license: "CC BY-SA 4.0", href: "https://commons.wikimedia.org/wiki/File%3AChris_Evans_at_the_2025_Toronto_International_Film_Festival_%28cropped%29.jpg" },
  { name: "Tom Hiddleston (×5)", credit: "Gage Skidmore", license: "CC BY-SA 2.0", href: "https://commons.wikimedia.org/wiki/File%3ATom_Hiddleston_%2827992871594%29.jpg" },
  { name: "Emma Watson (2010)", credit: "Joella Marano / derivative: Bff", license: "CC BY 2.0", href: "https://commons.wikimedia.org/wiki/File%3AEmmaWatsonNov2010-2.jpg" },
  { name: "Emma Watson (2012, a)", credit: "David Shankbone", license: "CC BY 3.0", href: "https://commons.wikimedia.org/wiki/File%3AEmma_Watson_2012_Shankbone_%28cropped%29.JPG" },
  { name: "Emma Watson (2012, b)", credit: "David Shankbone", license: "CC BY 2.0", href: "https://commons.wikimedia.org/wiki/File%3AEmma_Watson%2C_2012.jpg" },
  { name: "Emma Watson (2013)", credit: "Georges Biard", license: "CC BY-SA 3.0", href: "https://commons.wikimedia.org/wiki/File%3AEmma_Watson_2%2C_2013.jpg" },
  { name: "Emma Watson (GoF premiere)", credit: "Zaheer12a / derivative: Lošmi", license: "CC BY-SA 3.0", href: "https://commons.wikimedia.org/wiki/File%3AEmma_Watson_GoF_Premiere_Crop.jpg" },
  { name: "Emma Watson (2017)", credit: "Mars Films", license: "CC BY 3.0", href: "https://commons.wikimedia.org/wiki/File%3AEmma_Watson_interview_in_2017_%28cropped%29.jpg" },
];

export default function Footer() {
  return (
    <footer>
      <div className="footer-bottom">
        <div className="footer-top">
          <div>facematch</div>
          <div className="footer-links">
            <a href="#">Docs</a>
            <a href="#">Contact</a>
          </div>
        </div>
        <details className="credits">
          <summary>Demo photo credits</summary>
          <p>
            Photos of Tom Hiddleston, Chris Evans, and Emma Watson used above
            are real, unedited photos from Wikimedia Commons, released under
            licenses that permit reuse.
          </p>
          <ul>
            {PHOTO_CREDITS.map((c) => (
              <li key={c.href}>
                {c.name} — {c.credit},{" "}
                <a href={c.href} target="_blank" rel="noopener noreferrer">
                  {c.license}
                </a>
              </li>
            ))}
          </ul>
        </details>
      </div>
    </footer>
  );
}
