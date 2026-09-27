import Nav from "@/components/Nav";
import Hero from "@/components/Hero";
import HowItWorks from "@/components/HowItWorks";
import Demo from "@/components/Demo";
import Privacy from "@/components/Privacy";
import Pricing from "@/components/Pricing";
import Footer from "@/components/Footer";

export default function Home() {
  return (
    <div className="wrap">
      <Nav />
      <Hero />
      <HowItWorks />
      <Demo />
      <Privacy />
      <Pricing />
      <Footer />
    </div>
  );
}
