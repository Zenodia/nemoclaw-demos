import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ArrowLeft } from "lucide-react";
import { toast } from "sonner";

interface WhackGopherProps {
  onComplete: (score: number) => void;
  onBack: () => void;
}

interface Hole {
  id: number;
  hasGopher: boolean;
  wasHit: boolean;
}

const funHits = ["BONK!", "GOT 'EM!", "OUCH!", "POW!", "ZAP!", "BAM!"];
const gopherEmojis = ["🐹", "🐿️", "🦫", "🐰"];

export const WhackGopher = ({ onComplete, onBack }: WhackGopherProps) => {
  const [holes, setHoles] = useState<Hole[]>(
    Array.from({ length: 9 }, (_, i) => ({ id: i, hasGopher: false, wasHit: false }))
  );
  const [score, setScore] = useState(0);
  const [timeLeft, setTimeLeft] = useState(45);
  const [combo, setCombo] = useState(0);
  const [speed, setSpeed] = useState(1200);

  useEffect(() => {
    if (timeLeft > 0) {
      const gopherInterval = setInterval(() => {
        // Hide all gophers first
        setHoles(prev => prev.map(h => ({ ...h, hasGopher: false, wasHit: false })));

        // Show 1-3 random gophers
        setTimeout(() => {
          const numGophers = Math.floor(Math.random() * 2) + 1;
          const availableHoles = Array.from({ length: 9 }, (_, i) => i);
          
          for (let i = 0; i < numGophers; i++) {
            const randomIndex = Math.floor(Math.random() * availableHoles.length);
            const holeId = availableHoles.splice(randomIndex, 1)[0];
            
            setHoles(prev =>
              prev.map(h => (h.id === holeId ? { ...h, hasGopher: true } : h))
            );
          }
        }, 100);
      }, speed);

      // Increase difficulty over time
      if (timeLeft % 10 === 0 && speed > 600) {
        setSpeed(s => Math.max(600, s - 100));
      }

      return () => clearInterval(gopherInterval);
    } else {
      toast.success(`Time's up! You bonked ${score} gophers!`);
      setTimeout(() => onComplete(score), 1000);
    }
  }, [timeLeft, speed]);

  useEffect(() => {
    if (timeLeft > 0) {
      const timer = setTimeout(() => setTimeLeft(timeLeft - 1), 1000);
      return () => clearTimeout(timer);
    }
  }, [timeLeft]);

  useEffect(() => {
    if (combo > 0) {
      const comboTimer = setTimeout(() => setCombo(0), 3000);
      return () => clearTimeout(comboTimer);
    }
  }, [combo]);

  const handleWhack = (holeId: number) => {
    const hole = holes.find(h => h.id === holeId);
    if (!hole?.hasGopher || hole.wasHit) return;

    const newCombo = combo + 1;
    setCombo(newCombo);
    const points = 10 + Math.floor(newCombo / 3) * 5;
    setScore(score + points);

    setHoles(prev =>
      prev.map(h => (h.id === holeId ? { ...h, wasHit: true } : h))
    );

    const message = funHits[Math.floor(Math.random() * funHits.length)];
    toast.success(message, { duration: 600 });

    if (newCombo > 0 && newCombo % 5 === 0) {
      toast.success(`${newCombo}x STREAK! 🔥`, { duration: 1000 });
    }
  };

  return (
    <div className="container max-w-4xl mx-auto px-4 py-8 min-h-screen">
      <div className="mb-8">
        <Button variant="ghost" onClick={onBack} className="mb-4">
          <ArrowLeft className="w-4 h-4 mr-2" />
          Back to Menu
        </Button>

        <div className="flex justify-between items-center">
          <div>
            <h2 className="text-3xl font-bold text-foreground mb-2">🐹 Whack-a-Gopher</h2>
            <p className="text-muted-foreground">Bonk those silly critters!</p>
          </div>
          <div className="flex gap-6 text-right">
            <div>
              <p className="text-sm text-muted-foreground">Time</p>
              <p className="text-2xl font-bold text-foreground">{timeLeft}s</p>
            </div>
            {combo > 0 && (
              <div className="animate-pop">
                <p className="text-sm text-muted-foreground">Streak</p>
                <p className="text-2xl font-bold text-accent">{combo}🔥</p>
              </div>
            )}
            <div>
              <p className="text-sm text-muted-foreground">Score</p>
              <p className="text-2xl font-bold text-primary">{score}</p>
            </div>
          </div>
        </div>
      </div>

      <Card className="p-8 bg-card/50 backdrop-blur">
        <div className="grid grid-cols-3 gap-6">
          {holes.map((hole, index) => (
            <button
              key={hole.id}
              className="relative aspect-square rounded-2xl bg-muted border-4 border-border hover:border-primary/50 transition-all duration-200 overflow-hidden"
              onClick={() => handleWhack(hole.id)}
            >
              {/* Hole */}
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="w-20 h-20 rounded-full bg-background/80 border-4 border-border" />
              </div>

              {/* Gopher */}
              {hole.hasGopher && (
                <div
                  className={`absolute inset-0 flex items-center justify-center text-6xl transition-all duration-200 ${
                    hole.wasHit ? "scale-0 rotate-180" : "animate-pop"
                  }`}
                >
                  {gopherEmojis[index % gopherEmojis.length]}
                </div>
              )}

              {/* Hit effect */}
              {hole.wasHit && (
                <div className="absolute inset-0 flex items-center justify-center text-4xl font-black text-primary animate-pop">
                  💥
                </div>
              )}
            </button>
          ))}
        </div>

        <div className="mt-8 text-center">
          {speed < 900 && (
            <p className="text-sm text-accent font-semibold animate-pulse-glow">
              ⚡ SPEED MODE ACTIVATED ⚡
            </p>
          )}
        </div>
      </Card>

      <div className="mt-4 text-center text-sm text-muted-foreground">
        <p>Click fast for combos! Speed increases every 10 seconds! 🎯</p>
      </div>
    </div>
  );
};
