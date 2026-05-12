import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { ArrowLeft, Sparkles } from "lucide-react";
import { toast } from "sonner";

interface BubblePopProps {
  onComplete: (score: number) => void;
  onBack: () => void;
}

interface Bubble {
  id: number;
  x: number;
  y: number;
  size: number;
  color: string;
  speed: number;
  popped: boolean;
}

const colors = ["primary", "secondary", "accent", "success", "warning"];
const funMessages = ["POP!", "BOOM!", "NICE!", "YEAH!", "WOW!", "SWEET!", "KABOOM!", "ZAP!"];

export const BubblePop = ({ onComplete, onBack }: BubblePopProps) => {
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [score, setScore] = useState(0);
  const [timeLeft, setTimeLeft] = useState(45);
  const [combo, setCombo] = useState(0);
  const [lastPopMessage, setLastPopMessage] = useState("");

  useEffect(() => {
    // Spawn bubbles continuously
    const spawnInterval = setInterval(() => {
      if (timeLeft > 0) {
        const newBubble: Bubble = {
          id: Date.now() + Math.random(),
          x: Math.random() * 85,
          y: 100,
          size: 40 + Math.random() * 60,
          color: colors[Math.floor(Math.random() * colors.length)],
          speed: 0.3 + Math.random() * 0.5,
          popped: false,
        };
        setBubbles(prev => [...prev, newBubble]);
      }
    }, 800);

    return () => clearInterval(spawnInterval);
  }, [timeLeft]);

  useEffect(() => {
    // Move bubbles up
    const moveInterval = setInterval(() => {
      setBubbles(prev =>
        prev
          .map(bubble => ({
            ...bubble,
            y: bubble.y - bubble.speed,
          }))
          .filter(bubble => bubble.y > -10 && !bubble.popped)
      );
    }, 20);

    return () => clearInterval(moveInterval);
  }, []);

  useEffect(() => {
    if (timeLeft > 0) {
      const timer = setTimeout(() => setTimeLeft(timeLeft - 1), 1000);
      return () => clearTimeout(timer);
    } else {
      toast.success(`Time's up! You popped ${score} bubbles!`);
      setTimeout(() => onComplete(score), 1000);
    }
  }, [timeLeft]);

  useEffect(() => {
    if (combo > 0) {
      const comboTimer = setTimeout(() => setCombo(0), 2000);
      return () => clearTimeout(comboTimer);
    }
  }, [combo]);

  const handleBubblePop = (bubbleId: number, points: number) => {
    setBubbles(prev =>
      prev.map(b => (b.id === bubbleId ? { ...b, popped: true } : b))
    );

    const newCombo = combo + 1;
    setCombo(newCombo);
    const comboMultiplier = Math.min(Math.floor(newCombo / 3), 3);
    const totalPoints = points + comboMultiplier * 5;
    setScore(score + totalPoints);

    const message = funMessages[Math.floor(Math.random() * funMessages.length)];
    setLastPopMessage(message);

    if (newCombo % 5 === 0) {
      toast.success(`${newCombo}x COMBO! 🔥`, { duration: 1000 });
    }

    setTimeout(() => {
      setBubbles(prev => prev.filter(b => b.id !== bubbleId));
    }, 300);
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
            <h2 className="text-3xl font-bold text-foreground mb-2 flex items-center gap-2">
              <Sparkles className="w-8 h-8 text-primary animate-pulse-glow" />
              Bubble Pop Chaos
            </h2>
            <p className="text-muted-foreground">Pop 'em all! No thinking required!</p>
          </div>
          <div className="flex gap-6 text-right">
            <div>
              <p className="text-sm text-muted-foreground">Time</p>
              <p className="text-2xl font-bold text-foreground">{timeLeft}s</p>
            </div>
            {combo > 0 && (
              <div className="animate-pop">
                <p className="text-sm text-muted-foreground">Combo</p>
                <p className="text-2xl font-bold text-accent">{combo}x🔥</p>
              </div>
            )}
            <div>
              <p className="text-sm text-muted-foreground">Score</p>
              <p className="text-2xl font-bold text-primary">{score}</p>
            </div>
          </div>
        </div>
      </div>

      <div className="relative w-full h-[600px] bg-card/30 backdrop-blur rounded-2xl border-2 border-border overflow-hidden">
        {lastPopMessage && (
          <div className="absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 text-6xl font-black text-primary/50 animate-pop pointer-events-none z-50">
            {lastPopMessage}
          </div>
        )}
        
        {bubbles.map(bubble => (
          <button
            key={bubble.id}
            className={`absolute rounded-full bg-${bubble.color} border-4 border-${bubble.color}/30 cursor-pointer hover:scale-110 transition-all duration-200 animate-pulse-glow shadow-lg`}
            style={{
              left: `${bubble.x}%`,
              bottom: `${bubble.y}%`,
              width: `${bubble.size}px`,
              height: `${bubble.size}px`,
              opacity: bubble.popped ? 0 : 0.8,
              transform: bubble.popped ? "scale(1.5)" : "scale(1)",
              transition: bubble.popped ? "all 0.3s ease-out" : "none",
            }}
            onClick={() => handleBubblePop(bubble.id, Math.floor(bubble.size / 10))}
          >
            <div className="w-full h-full rounded-full bg-gradient-to-br from-white/30 to-transparent" />
          </button>
        ))}

        {bubbles.length === 0 && timeLeft > 0 && (
          <div className="absolute inset-0 flex items-center justify-center text-muted-foreground text-xl">
            Get ready...
          </div>
        )}
      </div>

      <div className="mt-4 text-center text-sm text-muted-foreground">
        <p>Pro tip: Build combos by popping bubbles quickly! 🎈</p>
      </div>
    </div>
  );
};
