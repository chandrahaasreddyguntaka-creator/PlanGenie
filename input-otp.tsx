import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Plane, Hotel, Map, Compass } from "lucide-react";
import { useNavigate } from "react-router-dom";

const Landing = () => {
  const navigate = useNavigate();

  const features = [
    {
      icon: Plane,
      title: "Smart Flight Search",
      description: "Find the best flights with AI-powered recommendations and real-time pricing."
    },
    {
      icon: Hotel,
      title: "Hotel Booking",
      description: "Discover perfect accommodations tailored to your preferences and budget."
    },
    {
      icon: Map,
      title: "Day-by-Day Itineraries",
      description: "Get personalized travel plans with activities, timings, and local insights."
    },
    {
      icon: Compass,
      title: "Activity Recommendations",
      description: "Explore curated experiences and hidden gems at your destination."
    }
  ];

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="container flex h-16 items-center justify-between">
          <div className="flex items-center gap-2">
            <Compass className="h-6 w-6 text-primary" />
            <span className="text-xl font-bold">PlanGenie</span>
          </div>
          <div className="flex items-center gap-3">
            <Button variant="ghost" onClick={() => navigate("/login")}>
              Log in
            </Button>
            <Button onClick={() => navigate("/signup")}>
              Sign up
            </Button>
          </div>
        </div>
      </header>

      {/* Hero Section */}
      <section className="container py-24">
        <div className="mx-auto max-w-3xl text-center">
          <h1 className="mb-6 text-5xl font-bold tracking-tight">
            Your AI Travel Planning Assistant
          </h1>
          <p className="mb-8 text-xl text-muted-foreground">
            Plan your perfect trip with intelligent flight search, hotel recommendations, 
            and personalized itineraries—all in one conversation.
          </p>
          <div className="flex flex-wrap justify-center gap-4">
            <Button size="lg" variant="outline" onClick={() => navigate("/signup")}>
              Sign up free
            </Button>
          </div>
        </div>
      </section>

      {/* Features Grid */}
      <section className="container pb-24">
        <div className="mx-auto max-w-5xl">
          <h2 className="mb-12 text-center text-3xl font-bold">Everything you need to plan your trip</h2>
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {features.map((feature) => (
              <Card key={feature.title}>
                <CardHeader>
                  <feature.icon className="mb-2 h-10 w-10 text-primary" />
                  <CardTitle className="text-lg">{feature.title}</CardTitle>
                </CardHeader>
                <CardContent>
                  <CardDescription>{feature.description}</CardDescription>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </section>

      {/* Screenshot Placeholder */}
      <section className="container pb-24">
        <div className="mx-auto max-w-5xl">
          <Card className="overflow-hidden">
            <div className="aspect-video bg-muted flex items-center justify-center">
              <p className="text-muted-foreground">Product Screenshot Placeholder</p>
            </div>
          </Card>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t py-8">
        <div className="container text-center text-sm text-muted-foreground">
          © 2025 PlanGenie. Built with React + Tailwind CSS.
        </div>
      </footer>
    </div>
  );
};

export default Landing;
