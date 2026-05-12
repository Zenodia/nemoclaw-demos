import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { ArrowLeft, MousePointerClick } from "lucide-react";

interface SpeedClickerProps {
  onComplete: (score: number) => void;
  onBack: () => void;
}

export const SpeedClicker = ({ onComplete, onBack }: SpeedClickerProps) => {
  const [clicks, setClicks] = useState(0);
  const [timeLeft, setTimeLeft] = useState(10);
  const [started, setStarted] = useState(false);
  const [cps, setCps] = useState(0);
  const [bestCps, setBestCps] = useState(0);

  useEffect(() => {
    if (!started) return;
    
    if (timeLeft <= 0) {
      const finalCps = clicks / 10;
      setCps(finalCps);
      if (finalCps > bestCps) setBestCps(finalCps);
      onComplete(clicks * 10);
      return;
    }
    
    const timer = setInterval(() => {
      setTimeLeft(prev => prev - 0.1);
      setCps(clicks / (10 - timeLeft));
    }, 100);
    
    return () => clearInterval(timer);
  }, [timeLeft, started, clicks, onComplete, bestCps]);

  const handleClick = () => {
    if (!started) {
      setStarted(true);
    }
    setClicks(prev => prev + 1);
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
            <div className="text-sm text-muted-foreground">Clicks</div>
            <div className="text-2xl font-bold text-primary">{clicks}</div>
          </div>
          <div className="text-center">
            <div className="text-sm text-muted-foreground">CPS</div>
            <div className="text-2xl font-bold text-secondary">{cps.toFixed(1)}</div>
          </div>
          {bestCps > 0 && (
            <div className="text-center">
              <div className="text-sm text-muted-foreground">Best</div>
              <div className="text-2xl font-bold text-accent">{bestCps.toFixed(1)}</div>
            </div>
          )}
        </div>
      </div>

      <div className="text-center mb-6">
        <div className="flex items-center justify-center gap-2 mb-2">
          <MousePointerClick className="w-6 h-6 text-primary" />
          <h2 className="text-3xl font-black text-foreground">Speed Clicker</h2>
        </div>
        <p className="text-muted-foreground">Click as fast as you can in 10 seconds!</p>
      </div>

      <div className="flex-1 flex items-center justify-center">
        <div className="text-center space-y-8">
          <div className="text-8xl font-black text-primary animate-pulse-glow">
            {timeLeft > 0 ? timeLeft.toFixed(1) : "TIME'S UP!"}
          </div>
          
          <Button
            onClick={handleClick}
            disabled={timeLeft <= 0}
            className="w-64 h-64 rounded-full text-4xl font-black bg-gradient-to-br from-primary via-secondary to-accent hover:scale-105 transition-transform duration-200 shadow-2xl"
          >
            {!started ? "START!" : "CLICK!"}
          </Button>

          {timeLeft <= 0 && (
            <div className="space-y-4 animate-fade-in">
              <p className="text-2xl font-bold text-foreground">
                You clicked {clicks} times!
              </p>
              <p className="text-xl text-muted-foreground">
                {cps.toFixed(2)} clicks per second
              </p>
              {cps >= 10 && (
                <p className="text-lg text-accent font-bold animate-pulse-glow">
                  🔥 AMAZING SPEED! 🔥
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
