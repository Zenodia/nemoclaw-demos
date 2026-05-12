import { useState } from "react";
import { GameMenu } from "@/components/game/GameMenu";
import { BubblePop } from "@/components/game/BubblePop";
import { SnackAttack } from "@/components/game/SnackAttack";
import { WhackGopher } from "@/components/game/WhackGopher";
import { ColorMatch } from "@/components/game/ColorMatch";
import { BalloonPop } from "@/components/game/BalloonPop";
import { ReactionTest } from "@/components/game/ReactionTest";
import { MemoryCards } from "@/components/game/MemoryCards";
import { SpeedClicker } from "@/components/game/SpeedClicker";
import { TargetPractice } from "@/components/game/TargetPractice";
import { GameComplete } from "@/components/game/GameComplete";

export type GameMode = "menu" | "bubble" | "snack" | "whack" | "complete" | "color" | "balloon" | "reaction" | "memory" | "clicker" | "target";

const Index = () => {
  const [gameMode, setGameMode] = useState<GameMode>("menu");
  const [totalScore, setTotalScore] = useState(0);

  const handleGameComplete = (score: number) => {
    setTotalScore(prev => prev + score);
    setGameMode("complete");
  };

  const handlePlayAgain = () => {
    setGameMode("menu");
  };

  const handleNextGame = () => {
    setGameMode("menu");
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-background via-card to-background overflow-hidden">
      {gameMode === "menu" && <GameMenu onSelectGame={setGameMode} totalScore={totalScore} />}
      {gameMode === "bubble" && <BubblePop onComplete={handleGameComplete} onBack={() => setGameMode("menu")} />}
      {gameMode === "snack" && <SnackAttack onComplete={handleGameComplete} onBack={() => setGameMode("menu")} />}
      {gameMode === "whack" && <WhackGopher onComplete={handleGameComplete} onBack={() => setGameMode("menu")} />}
      {gameMode === "color" && <ColorMatch onComplete={handleGameComplete} onBack={() => setGameMode("menu")} />}
      {gameMode === "balloon" && <BalloonPop onComplete={handleGameComplete} onBack={() => setGameMode("menu")} />}
      {gameMode === "reaction" && <ReactionTest onComplete={handleGameComplete} onBack={() => setGameMode("menu")} />}
      {gameMode === "memory" && <MemoryCards onComplete={handleGameComplete} onBack={() => setGameMode("menu")} />}
      {gameMode === "clicker" && <SpeedClicker onComplete={handleGameComplete} onBack={() => setGameMode("menu")} />}
      {gameMode === "target" && <TargetPractice onComplete={handleGameComplete} onBack={() => setGameMode("menu")} />}
      {gameMode === "complete" && <GameComplete score={totalScore} onPlayAgain={handlePlayAgain} onNextGame={handleNextGame} />}
    </div>
  );
};

export default Index;
