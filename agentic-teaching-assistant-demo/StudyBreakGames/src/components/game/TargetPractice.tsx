import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { ArrowLeft, Target } from "lucide-react";

interface TargetPracticeProps {
  onComplete: (score: number) => void;
  onBack: () => void;
}

interface TargetCircle {
  id: number;
  x: number;
  y: number;
  rings: number;
}

export const TargetPractice = ({ onComplete, onBack }: TargetPracticeProps) => {
  const [target, setTarget] = useState<TargetCircle | null>(null);
  const [score, setScore] = useState(0);
  const [shots, setShots] = useState(0);
  const [accuracy, setAccuracy] = useState(0);
  const [hits, setHits] = useState(0);
  const maxShots = 15;

  useEffect(() => {
    spawnTarget();
  }, []);

  useEffect(() => {
    if (shots >= maxShots) {
      onComplete(score);
    }
  }, [shots, score, onComplete]);

  const spawnTarget = () => {
    const newTarget: TargetCircle = {
      id: Date.now(),
      x: Math.random() * 70 + 15,
      y: Math.random() * 60 + 20,
      rings: 4,
    };
    setTarget(newTarget);
  };

  const handleShot = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!target || shots >= maxShots) return;
    
    const rect = e.currentTarget.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const clickY = e.clientY - rect.top;
    
    const targetX = (target.x / 100) * rect.width;
    const targetY = (target.y / 100) * rect.height;
    
    const distance = Math.sqrt(
      Math.pow(clickX - targetX, 2) + Math.pow(clickY - targetY, 2)
    );
    
    let points = 0;
    if (distance < 20) points = 100; // Bullseye
    else if (distance < 40) points = 50;
    else if (distance < 60) points = 25;
    else if (distance < 80) points = 10;
    
    if (points > 0) {
      setHits(prev => prev + 1);
      setScore(prev => prev + points);
    }
    
    setShots(prev => prev + 1);
    setAccuracy(Math.round(((hits + (points > 0 ? 1 : 0)) / (shots + 1)) * 100));
    
    setTimeout(() => {
      if (shots + 1 < maxShots) {
        spawnTarget();
      }
    }, 300);
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
            <div className="text-sm text-muted-foreground">Shots</div>
            <div className="text-2xl font-bold text-secondary">{shots}/{maxShots}</div>
          </div>
          <div className="text-center">
            <div className="text-sm text-muted-foreground">Accuracy</div>
            <div className="text-2xl font-bold text-accent">{accuracy}%</div>
          </div>
        </div>
      </div>

      <div className="text-center mb-6">
        <div className="flex items-center justify-center gap-2 mb-2">
          <Target className="w-6 h-6 text-primary" />
          <h2 className="text-3xl font-black text-foreground">Target Practice</h2>
        </div>
        <p className="text-muted-foreground">Hit the bullseye for maximum points!</p>
      </div>

      <div 
        className="flex-1 relative bg-gradient-to-br from-card to-background rounded-2xl border-2 border-border overflow-hidden cursor-crosshair"
        onClick={handleShot}
      >
        {target && shots < maxShots && (
          <div
            className="absolute transform -translate-x-1/2 -translate-y-1/2"
            style={{
              left: `${target.x}%`,
              top: `${target.y}%`,
            }}
          >
            <div className="relative w-40 h-40">
              <div className="absolute inset-0 rounded-full bg-destructive" />
              <div className="absolute inset-4 rounded-full bg-card" />
              <div className="absolute inset-8 rounded-full bg-secondary" />
              <div className="absolute inset-12 rounded-full bg-card" />
              <div className="absolute inset-16 rounded-full bg-primary animate-pulse-glow" />
            </div>
          </div>
        )}
        {shots >= maxShots && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center space-y-4 animate-fade-in">
              <p className="text-3xl font-black text-foreground">Game Over!</p>
              <p className="text-xl text-muted-foreground">Final Score: {score}</p>
              <p className="text-lg text-muted-foreground">Accuracy: {accuracy}%</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
