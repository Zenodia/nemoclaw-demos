import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { ArrowLeft, Wind } from "lucide-react";

interface BalloonPopProps {
  onComplete: (score: number) => void;
  onBack: () => void;
}

interface Balloon {
  id: number;
  x: number;
  y: number;
  color: string;
  speed: number;
  popped: boolean;
}

export const BalloonPop = ({ onComplete, onBack }: BalloonPopProps) => {
  const [balloons, setBalloons] = useState<Balloon[]>([]);
  const [score, setScore] = useState(0);
  const [timeLeft, setTimeLeft] = useState(45);
  const [missed, setMissed] = useState(0);

  useEffect(() => {
    const spawnInterval = setInterval(() => {
      const newBalloon: Balloon = {
        id: Date.now(),
        x: Math.random() * 80 + 10,
        y: 100,
        color: ["#ef4444", "#3b82f6", "#22c55e", "#eab308", "#a855f7"][Math.floor(Math.random() * 5)],
        speed: Math.random() * 1.5 + 1,
        popped: false,
      };
      setBalloons(prev => [...prev, newBalloon]);
    }, 1000);

    return () => clearInterval(spawnInterval);
  }, []);

  useEffect(() => {
    const moveInterval = setInterval(() => {
      setBalloons(prev => prev.map(balloon => {
        if (balloon.popped) return balloon;
        const newY = balloon.y - balloon.speed;
        if (newY < -10) {
          setMissed(m => m + 1);
          return { ...balloon, y: -20 };
        }
        return { ...balloon, y: newY };
      }).filter(b => b.y > -15 || b.popped));
    }, 50);

    return () => clearInterval(moveInterval);
  }, []);

  useEffect(() => {
    if (timeLeft <= 0 || missed >= 10) {
      onComplete(score);
      return;
    }
    const timer = setInterval(() => setTimeLeft(prev => prev - 1), 1000);
    return () => clearInterval(timer);
  }, [timeLeft, missed, score, onComplete]);

  const handlePop = (id: number) => {
    setBalloons(prev => prev.map(b => 
      b.id === id ? { ...b, popped: true } : b
    ));
    setScore(prev => prev + 10);
    setTimeout(() => {
      setBalloons(prev => prev.filter(b => b.id !== id));
    }, 200);
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
            <div className="text-sm text-muted-foreground">Time</div>
            <div className="text-2xl font-bold text-secondary">{timeLeft}s</div>
          </div>
          <div className="text-center">
            <div className="text-sm text-muted-foreground">Missed</div>
            <div className="text-2xl font-bold text-destructive">{missed}/10</div>
          </div>
        </div>
      </div>

      <div className="text-center mb-6">
        <div className="flex items-center justify-center gap-2 mb-2">
          <Wind className="w-6 h-6 text-primary" />
          <h2 className="text-3xl font-black text-foreground">Balloon Pop</h2>
        </div>
        <p className="text-muted-foreground">Pop balloons before they fly away!</p>
      </div>

      <div className="flex-1 relative bg-gradient-to-b from-card to-background rounded-2xl border-2 border-border overflow-hidden">
        {balloons.map(balloon => (
          <div
            key={balloon.id}
            onClick={() => !balloon.popped && handlePop(balloon.id)}
            className={`absolute cursor-pointer transition-all duration-200 ${
              balloon.popped ? 'scale-0' : 'hover:scale-110'
            }`}
            style={{
              left: `${balloon.x}%`,
              bottom: `${balloon.y}%`,
              transform: 'translateX(-50%)',
            }}
          >
            <div className="relative">
              <div
                className="w-16 h-20 rounded-full shadow-lg"
                style={{ backgroundColor: balloon.color }}
              />
              <div className="absolute top-full left-1/2 w-0.5 h-12 bg-muted-foreground/30" />
            </div>
          </div>
        ))}
        {balloons.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center text-muted-foreground">
            Balloons incoming...
          </div>
        )}
      </div>
    </div>
  );
};
