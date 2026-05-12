import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { ArrowLeft, Zap } from "lucide-react";

interface ReactionTestProps {
  onComplete: (score: number) => void;
  onBack: () => void;
}

interface Target {
  id: number;
  x: number;
  y: number;
  size: number;
  spawnTime: number;
}

export const ReactionTest = ({ onComplete, onBack }: ReactionTestProps) => {
  const [target, setTarget] = useState<Target | null>(null);
  const [score, setScore] = useState(0);
  const [hits, setHits] = useState(0);
  const [avgReaction, setAvgReaction] = useState(0);
  const [reactions, setReactions] = useState<number[]>([]);
  const [round, setRound] = useState(0);
  const maxRounds = 15;

  useEffect(() => {
    if (round >= maxRounds) {
      onComplete(score);
      return;
    }

    const delay = Math.random() * 2000 + 1000;
    const timeout = setTimeout(() => {
      spawnTarget();
    }, delay);

    return () => clearTimeout(timeout);
  }, [round]);

  const spawnTarget = () => {
    const newTarget: Target = {
      id: Date.now(),
      x: Math.random() * 70 + 15,
      y: Math.random() * 60 + 20,
      size: Math.random() * 30 + 40,
      spawnTime: Date.now(),
    };
    setTarget(newTarget);
  };

  const handleHit = () => {
    if (!target) return;

    const reactionTime = Date.now() - target.spawnTime;
    const newReactions = [...reactions, reactionTime];
    setReactions(newReactions);
    
    const points = Math.max(100 - Math.floor(reactionTime / 10), 10);
    setScore(prev => prev + points);
    setHits(prev => prev + 1);
    setAvgReaction(Math.round(newReactions.reduce((a, b) => a + b, 0) / newReactions.length));
    
    setTarget(null);
    setRound(prev => prev + 1);
  };

  const handleMiss = () => {
    if (target) {
      setTarget(null);
      setRound(prev => prev + 1);
    }
  };

  return (
    <div className="container max-w-6xl mx-auto px-4 py-8 min-h-screen flex flex-col">
      <div className="flex justify-between items-center mb-8">
        <Button variant="outline" onClick={onBack} className="gap-2">
          <ArrowLeft className="w-4 h-4" />
          Back
        </Button>
        <div className="flex gap-6">
          <div className="text-center">
            <div className="text-sm text-muted-foreground">Score</div>
            <div className="text-2xl font-bold text-primary">{score}</div>
          </div>
          <div className="text-center">
            <div className="text-sm text-muted-foreground">Round</div>
            <div className="text-2xl font-bold text-secondary">{round}/{maxRounds}</div>
          </div>
          <div className="text-center">
            <div className="text-sm text-muted-foreground">Avg Time</div>
            <div className="text-2xl font-bold text-accent">{avgReaction}ms</div>
          </div>
        </div>
      </div>

      <div className="text-center mb-6">
        <div className="flex items-center justify-center gap-2 mb-2">
          <Zap className="w-6 h-6 text-primary" />
          <h2 className="text-3xl font-black text-foreground">Reaction Test</h2>
        </div>
        <p className="text-muted-foreground">Click the targets as fast as you can!</p>
      </div>

      <div 
        className="flex-1 relative bg-gradient-to-br from-card to-background rounded-2xl border-2 border-border overflow-hidden cursor-crosshair"
        onClick={handleMiss}
      >
        {target && (
          <div
            onClick={(e) => {
              e.stopPropagation();
              handleHit();
            }}
            className="absolute animate-pulse-glow cursor-pointer hover:scale-110 transition-transform"
            style={{
              left: `${target.x}%`,
              top: `${target.y}%`,
              width: `${target.size}px`,
              height: `${target.size}px`,
            }}
          >
            <div className="w-full h-full rounded-full bg-gradient-to-br from-primary to-secondary shadow-lg flex items-center justify-center">
              <Zap className="w-1/2 h-1/2 text-primary-foreground" />
            </div>
          </div>
        )}
        {!target && round < maxRounds && (
          <div className="absolute inset-0 flex items-center justify-center text-muted-foreground text-xl">
            Get ready...
          </div>
        )}
      </div>
    </div>
  );
};
