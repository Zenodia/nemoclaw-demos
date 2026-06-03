import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Trophy, RotateCcw, ArrowRight } from "lucide-react";

interface GameCompleteProps {
  score: number;
  onPlayAgain: () => void;
  onNextGame: () => void;
}

export const GameComplete = ({ score, onPlayAgain, onNextGame }: GameCompleteProps) => {
  const getRank = () => {
    if (score >= 200) return { title: "UNSTOPPABLE!", emoji: "🔥", color: "text-accent" };
    if (score >= 150) return { title: "Awesome!", emoji: "🎉", color: "text-primary" };
    if (score >= 100) return { title: "Pretty Good!", emoji: "😎", color: "text-secondary" };
    return { title: "Not Bad!", emoji: "👍", color: "text-muted-foreground" };
  };

  const rank = getRank();

  return (
    <div className="container max-w-2xl mx-auto px-4 py-8 min-h-screen flex items-center justify-center">
      <Card className="w-full p-12 bg-card/50 backdrop-blur text-center animate-pop">
        <div className="mb-8">
          <div className="w-24 h-24 mx-auto mb-6 rounded-full bg-gradient-to-br from-primary/20 to-secondary/20 flex items-center justify-center animate-pulse-glow">
            <Trophy className="w-12 h-12 text-primary" />
          </div>
          <p className="text-6xl mb-4 animate-float">{rank.emoji}</p>
          <h2 className={`text-4xl font-bold mb-4 ${rank.color}`}>{rank.title}</h2>
          <p className="text-muted-foreground mb-8">You've completed the game!</p>
        </div>

        <div className="mb-12">
          <p className="text-lg text-muted-foreground mb-2">Total Score</p>
          <p className="text-6xl font-black bg-gradient-to-r from-primary via-secondary to-accent bg-clip-text text-transparent">
            {score}
          </p>
        </div>

        <div className="flex gap-4 justify-center">
          <Button
            size="lg"
            variant="outline"
            onClick={onPlayAgain}
            className="font-semibold"
          >
            <RotateCcw className="w-4 h-4 mr-2" />
            Play Again
          </Button>
          <Button
            size="lg"
            onClick={onNextGame}
            className="bg-primary hover:bg-primary/90 text-primary-foreground font-semibold"
          >
            Next Game
            <ArrowRight className="w-4 h-4 ml-2" />
          </Button>
        </div>

        <p className="mt-8 text-sm text-muted-foreground">
          Feel refreshed? Your brain is ready to tackle those books again! 📚✨
        </p>
      </Card>
    </div>
  );
};
