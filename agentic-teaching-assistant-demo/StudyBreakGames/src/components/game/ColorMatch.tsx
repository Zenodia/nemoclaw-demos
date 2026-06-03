import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { ArrowLeft, Palette } from "lucide-react";

interface ColorMatchProps {
  onComplete: (score: number) => void;
  onBack: () => void;
}

const COLORS = [
  { name: "Red", hex: "#ef4444", rgb: "239, 68, 68" },
  { name: "Blue", hex: "#3b82f6", rgb: "59, 130, 246" },
  { name: "Green", hex: "#22c55e", rgb: "34, 197, 94" },
  { name: "Yellow", hex: "#eab308", rgb: "234, 179, 8" },
  { name: "Purple", hex: "#a855f7", rgb: "168, 85, 247" },
  { name: "Orange", hex: "#f97316", rgb: "249, 115, 22" },
];

export const ColorMatch = ({ onComplete, onBack }: ColorMatchProps) => {
  const [score, setScore] = useState(0);
  const [timeLeft, setTimeLeft] = useState(30);
  const [targetColor, setTargetColor] = useState(COLORS[0]);
  const [displayedWord, setDisplayedWord] = useState(COLORS[0]);
  const [wordColor, setWordColor] = useState(COLORS[0]);
  const [streak, setStreak] = useState(0);

  useEffect(() => {
    generateNewChallenge();
  }, []);

  useEffect(() => {
    if (timeLeft <= 0) {
      onComplete(score);
      return;
    }
    const timer = setInterval(() => setTimeLeft(prev => prev - 1), 1000);
    return () => clearInterval(timer);
  }, [timeLeft, score, onComplete]);

  const generateNewChallenge = () => {
    const randomTarget = COLORS[Math.floor(Math.random() * COLORS.length)];
    const randomWord = COLORS[Math.floor(Math.random() * COLORS.length)];
    const randomColor = COLORS[Math.floor(Math.random() * COLORS.length)];
    
    setTargetColor(randomTarget);
    setDisplayedWord(randomWord);
    setWordColor(randomColor);
  };

  const handleAnswer = (matchesTarget: boolean) => {
    const isCorrect = matchesTarget === (wordColor.name === targetColor.name);
    
    if (isCorrect) {
      const points = 10 + (streak * 2);
      setScore(prev => prev + points);
      setStreak(prev => prev + 1);
    } else {
      setStreak(0);
    }
    
    generateNewChallenge();
  };

  return (
    <div className="container max-w-4xl mx-auto px-4 py-8 min-h-screen flex flex-col">
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
          {streak > 0 && (
            <div className="text-center animate-pulse-glow">
              <div className="text-sm text-muted-foreground">Streak</div>
              <div className="text-2xl font-bold text-accent">{streak}🔥</div>
            </div>
          )}
        </div>
      </div>

      <div className="flex-1 flex flex-col items-center justify-center gap-12">
        <div className="text-center">
          <div className="flex items-center justify-center gap-2 mb-4">
            <Palette className="w-8 h-8 text-primary" />
            <h2 className="text-4xl font-black text-foreground">Color Match</h2>
          </div>
          <p className="text-muted-foreground">Does the COLOR match the target?</p>
        </div>

        <div className="bg-card border-2 border-primary rounded-2xl p-8 text-center min-w-[400px]">
          <div className="mb-6">
            <p className="text-sm text-muted-foreground mb-2">Target Color:</p>
            <div 
              className="mx-auto w-32 h-32 rounded-xl shadow-lg"
              style={{ backgroundColor: targetColor.hex }}
            />
            <p className="text-xl font-bold mt-2 text-foreground">{targetColor.name}</p>
          </div>

          <div className="my-8 border-t-2 border-border pt-8">
            <p className="text-sm text-muted-foreground mb-4">Does this match?</p>
            <div 
              className="text-6xl font-black mb-4"
              style={{ color: wordColor.hex }}
            >
              {displayedWord.name}
            </div>
          </div>
        </div>

        <div className="flex gap-4">
          <Button
            onClick={() => handleAnswer(true)}
            className="px-12 py-6 text-xl font-bold bg-primary hover:bg-primary/90"
          >
            ✓ Yes
          </Button>
          <Button
            onClick={() => handleAnswer(false)}
            className="px-12 py-6 text-xl font-bold bg-secondary hover:bg-secondary/90"
          >
            ✗ No
          </Button>
        </div>
      </div>
    </div>
  );
};
