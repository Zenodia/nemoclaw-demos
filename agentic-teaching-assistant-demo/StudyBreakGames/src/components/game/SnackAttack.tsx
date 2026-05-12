import { useState, useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { ArrowLeft, Heart } from "lucide-react";
import { toast } from "sonner";

interface SnackAttackProps {
  onComplete: (score: number) => void;
  onBack: () => void;
}

interface FallingItem {
  id: number;
  x: number;
  y: number;
  emoji: string;
  isGood: boolean;
  speed: number;
}

const goodSnacks = ["🍕", "🍔", "🍟", "🌭", "🍩", "🍪", "🍦", "🍰"];
const badSnacks = ["🥗", "🥦", "🥕", "🍎", "🥒"];
const funCatches = ["Yum!", "Tasty!", "Nom nom!", "Delicious!", "More!", "Yeah!"];
const funMisses = ["Oops!", "Oh no!", "Missed it!", "Dang!"];

export const SnackAttack = ({ onComplete, onBack }: SnackAttackProps) => {
  const [items, setItems] = useState<FallingItem[]>([]);
  const [basketX, setBasketX] = useState(50);
  const [score, setScore] = useState(0);
  const [lives, setLives] = useState(3);
  const [timeLeft, setTimeLeft] = useState(60);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const spawnInterval = setInterval(() => {
      if (timeLeft > 0 && lives > 0) {
        const isGood = Math.random() > 0.25;
        const snackArray = isGood ? goodSnacks : badSnacks;
        const newItem: FallingItem = {
          id: Date.now() + Math.random(),
          x: Math.random() * 85,
          y: 0,
          emoji: snackArray[Math.floor(Math.random() * snackArray.length)],
          isGood,
          speed: 1 + Math.random() * 1.5,
        };
        setItems(prev => [...prev, newItem]);
      }
    }, 1000);

    return () => clearInterval(spawnInterval);
  }, [timeLeft, lives]);

  useEffect(() => {
    const moveInterval = setInterval(() => {
      setItems(prev =>
        prev
          .map(item => ({
            ...item,
            y: item.y + item.speed,
          }))
          .filter(item => {
            if (item.y > 85) {
              // Check if caught by basket
              if (Math.abs(item.x - basketX) < 8) {
                if (item.isGood) {
                  setScore(s => s + 10);
                  toast.success(funCatches[Math.floor(Math.random() * funCatches.length)], {
                    duration: 800,
                  });
                } else {
                  setLives(l => Math.max(0, l - 1));
                  toast.error("Eww, healthy food! 🤢", { duration: 1000 });
                }
                return false;
              }
              // Missed a good snack
              if (item.isGood) {
                setLives(l => Math.max(0, l - 1));
                toast.error(funMisses[Math.floor(Math.random() * funMisses.length)], {
                  duration: 800,
                });
              }
              return false;
            }
            return item.y < 100;
          })
      );
    }, 30);

    return () => clearInterval(moveInterval);
  }, [basketX]);

  useEffect(() => {
    if (timeLeft > 0 && lives > 0) {
      const timer = setTimeout(() => setTimeLeft(timeLeft - 1), 1000);
      return () => clearTimeout(timer);
    } else {
      const finalScore = score + lives * 20;
      toast.success(lives === 0 ? "Game over!" : "Time's up!");
      setTimeout(() => onComplete(finalScore), 1000);
    }
  }, [timeLeft, lives]);

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * 100;
    setBasketX(Math.max(5, Math.min(95, x)));
  };

  return (
    <div className="container max-w-6xl mx-auto px-4 py-8 min-h-screen">
      <div className="mb-8">
        <Button variant="ghost" onClick={onBack} className="mb-4">
          <ArrowLeft className="w-4 h-4 mr-2" />
          Back to Menu
        </Button>

        <div className="flex justify-between items-center">
          <div>
            <h2 className="text-3xl font-bold text-foreground mb-2">🍕 Snack Attack</h2>
            <p className="text-muted-foreground">Catch the junk food, avoid the healthy stuff!</p>
          </div>
          <div className="flex gap-6 text-right">
            <div>
              <p className="text-sm text-muted-foreground">Time</p>
              <p className="text-2xl font-bold text-foreground">{timeLeft}s</p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Lives</p>
              <div className="flex gap-1">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Heart
                    key={i}
                    className={`w-6 h-6 ${
                      i < lives ? "fill-destructive text-destructive" : "text-muted"
                    }`}
                  />
                ))}
              </div>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Score</p>
              <p className="text-2xl font-bold text-primary">{score}</p>
            </div>
          </div>
        </div>
      </div>

      <div
        ref={containerRef}
        className="relative w-full h-[600px] bg-card/30 backdrop-blur rounded-2xl border-2 border-border overflow-hidden cursor-none"
        onMouseMove={handleMouseMove}
      >
        {items.map(item => (
          <div
            key={item.id}
            className="absolute text-5xl animate-float pointer-events-none"
            style={{
              left: `${item.x}%`,
              top: `${item.y}%`,
              transform: "translate(-50%, -50%)",
            }}
          >
            {item.emoji}
          </div>
        ))}

        {/* Basket */}
        <div
          className="absolute bottom-4 transition-all duration-100 ease-out"
          style={{
            left: `${basketX}%`,
            transform: "translateX(-50%)",
          }}
        >
          <div className="text-6xl">🧺</div>
        </div>

        {items.length === 0 && timeLeft > 0 && (
          <div className="absolute inset-0 flex items-center justify-center text-muted-foreground text-xl">
            Move your mouse to control the basket!
          </div>
        )}
      </div>

      <div className="mt-4 text-center text-sm text-muted-foreground">
        <p>Disclaimer: We love vegetables... just not in this game 😄</p>
      </div>
    </div>
  );
};
