import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Sparkles, Pizza, Squirrel, Trophy, Palette, Wind, Zap, Brain, MousePointerClick, Target } from "lucide-react";
import { GameMode } from "@/pages/Index";

interface GameMenuProps {
  onSelectGame: (mode: GameMode) => void;
  totalScore: number;
}

export const GameMenu = ({ onSelectGame, totalScore }: GameMenuProps) => {
  const games = [
    {
      id: "bubble" as GameMode,
      title: "Bubble Pop Chaos",
      description: "Pop bubbles like there's no tomorrow!",
      icon: Sparkles,
      color: "from-primary to-secondary",
    },
    {
      id: "snack" as GameMode,
      title: "Snack Attack",
      description: "Catch snacks, dodge veggies!",
      icon: Pizza,
      color: "from-secondary to-accent",
    },
    {
      id: "whack" as GameMode,
      title: "Whack-a-Gopher",
      description: "Bonk those silly gophers!",
      icon: Squirrel,
      color: "from-accent to-primary",
    },
    {
      id: "color" as GameMode,
      title: "Color Match",
      description: "Test your brain with color challenges!",
      icon: Palette,
      color: "from-primary to-accent",
    },
    {
      id: "balloon" as GameMode,
      title: "Balloon Pop",
      description: "Pop balloons before they fly away!",
      icon: Wind,
      color: "from-secondary to-primary",
    },
    {
      id: "reaction" as GameMode,
      title: "Reaction Test",
      description: "How fast are your reflexes?",
      icon: Zap,
      color: "from-accent to-secondary",
    },
    {
      id: "memory" as GameMode,
      title: "Memory Match",
      description: "Find all the matching pairs!",
      icon: Brain,
      color: "from-primary to-secondary",
    },
    {
      id: "clicker" as GameMode,
      title: "Speed Clicker",
      description: "Click as fast as humanly possible!",
      icon: MousePointerClick,
      color: "from-secondary to-accent",
    },
    {
      id: "target" as GameMode,
      title: "Target Practice",
      description: "Hit the bullseye for maximum points!",
      icon: Target,
      color: "from-accent to-primary",
    },
  ];

  return (
    <div className="container max-w-6xl mx-auto px-4 py-8 min-h-screen flex flex-col items-center justify-center">
      <div className="text-center mb-12 animate-slide-up">
        <h1 className="text-6xl font-black mb-4 bg-gradient-to-r from-primary via-secondary to-accent bg-clip-text text-transparent">
          Study Break Zone
        </h1>
        <p className="text-xl text-muted-foreground mb-6">Your brain needs a vacation! 🎮</p>
        {totalScore > 0 && (
          <div className="inline-flex items-center gap-2 px-6 py-3 bg-card rounded-full border-2 border-primary animate-pulse-glow">
            <Trophy className="w-6 h-6 text-accent" />
            <span className="text-2xl font-bold text-foreground">{totalScore}</span>
            <span className="text-muted-foreground">points</span>
          </div>
        )}
      </div>

      <div className="grid md:grid-cols-3 gap-6 w-full max-w-4xl">
        {games.map((game, index) => {
          const Icon = game.icon;
          return (
            <Card
              key={game.id}
              className="relative overflow-hidden border-2 border-border hover:border-primary transition-all duration-300 hover:scale-105 cursor-pointer group bg-card/50 backdrop-blur"
              onClick={() => onSelectGame(game.id)}
              style={{ animationDelay: `${index * 100}ms` }}
            >
              <div className={`absolute inset-0 bg-gradient-to-br ${game.color} opacity-0 group-hover:opacity-10 transition-opacity duration-300`} />
              <div className="p-8 relative z-10">
                <div className="mb-6 flex justify-center">
                  <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-primary/20 to-secondary/20 flex items-center justify-center group-hover:scale-110 transition-transform duration-300">
                    <Icon className="w-10 h-10 text-primary" />
                  </div>
                </div>
                <h3 className="text-2xl font-bold mb-3 text-center text-foreground">{game.title}</h3>
                <p className="text-muted-foreground text-center mb-6">{game.description}</p>
                <Button className="w-full bg-primary hover:bg-primary/90 text-primary-foreground font-semibold">
                  Play Now
                </Button>
              </div>
            </Card>
          );
        })}
      </div>

      <div className="mt-12 text-center text-sm text-muted-foreground">
        <p>Zero thinking required • Maximum fun guaranteed • Perfect procrastination 🎉</p>
      </div>
    </div>
  );
};
