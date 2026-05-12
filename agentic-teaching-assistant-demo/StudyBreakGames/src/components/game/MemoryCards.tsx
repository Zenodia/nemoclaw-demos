import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { ArrowLeft, Brain } from "lucide-react";

interface MemoryCardsProps {
  onComplete: (score: number) => void;
  onBack: () => void;
}

interface Card {
  id: number;
  emoji: string;
  matched: boolean;
  flipped: boolean;
}

const EMOJIS = ["🎮", "🎯", "🎨", "🎭", "🎪", "🎸", "🎺", "🎹"];

export const MemoryCards = ({ onComplete, onBack }: MemoryCardsProps) => {
  const [cards, setCards] = useState<Card[]>([]);
  const [flippedIndices, setFlippedIndices] = useState<number[]>([]);
  const [score, setScore] = useState(0);
  const [moves, setMoves] = useState(0);
  const [matches, setMatches] = useState(0);
  const [timeLeft, setTimeLeft] = useState(60);

  useEffect(() => {
    initializeGame();
  }, []);

  useEffect(() => {
    if (timeLeft <= 0 || matches === 8) {
      onComplete(score);
      return;
    }
    const timer = setInterval(() => setTimeLeft(prev => prev - 1), 1000);
    return () => clearInterval(timer);
  }, [timeLeft, matches, score, onComplete]);

  useEffect(() => {
    if (flippedIndices.length === 2) {
      setMoves(prev => prev + 1);
      const [first, second] = flippedIndices;
      if (cards[first].emoji === cards[second].emoji) {
        setScore(prev => prev + 50);
        setMatches(prev => prev + 1);
        setTimeout(() => {
          setCards(prev => prev.map((card, idx) => 
            idx === first || idx === second ? { ...card, matched: true } : card
          ));
          setFlippedIndices([]);
        }, 500);
      } else {
        setTimeout(() => {
          setCards(prev => prev.map((card, idx) => 
            idx === first || idx === second ? { ...card, flipped: false } : card
          ));
          setFlippedIndices([]);
        }, 1000);
      }
    }
  }, [flippedIndices, cards]);

  const initializeGame = () => {
    const doubled = [...EMOJIS, ...EMOJIS];
    const shuffled = doubled
      .sort(() => Math.random() - 0.5)
      .map((emoji, idx) => ({
        id: idx,
        emoji,
        matched: false,
        flipped: false,
      }));
    setCards(shuffled);
  };

  const handleCardClick = (index: number) => {
    if (flippedIndices.length === 2 || cards[index].flipped || cards[index].matched) return;
    
    setCards(prev => prev.map((card, idx) => 
      idx === index ? { ...card, flipped: true } : card
    ));
    setFlippedIndices(prev => [...prev, index]);
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
            <div className="text-sm text-muted-foreground">Moves</div>
            <div className="text-2xl font-bold text-secondary">{moves}</div>
          </div>
          <div className="text-center">
            <div className="text-sm text-muted-foreground">Time</div>
            <div className="text-2xl font-bold text-accent">{timeLeft}s</div>
          </div>
        </div>
      </div>

      <div className="text-center mb-6">
        <div className="flex items-center justify-center gap-2 mb-2">
          <Brain className="w-6 h-6 text-primary" />
          <h2 className="text-3xl font-black text-foreground">Memory Match</h2>
        </div>
        <p className="text-muted-foreground">Find all the matching pairs!</p>
      </div>

      <div className="grid grid-cols-4 gap-4 max-w-lg mx-auto">
        {cards.map((card, index) => (
          <div
            key={card.id}
            onClick={() => handleCardClick(index)}
            className={`aspect-square rounded-xl cursor-pointer transition-all duration-300 transform ${
              card.flipped || card.matched
                ? 'bg-gradient-to-br from-primary to-secondary scale-105'
                : 'bg-card border-2 border-border hover:scale-105'
            } ${card.matched ? 'opacity-50' : ''}`}
          >
            <div className="w-full h-full flex items-center justify-center text-4xl">
              {(card.flipped || card.matched) ? card.emoji : '?'}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
