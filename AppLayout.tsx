import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { CheckCircle2, Circle } from "lucide-react";
import { cn } from "@/lib/utils";

interface ThoughtStep {
  id: string;
  text: string;
  completed: boolean;
  timestamp: number;
}

interface ChainOfThoughtProps {
  steps: ThoughtStep[];
  isActive: boolean;
}

export function ChainOfThought({ steps, isActive }: ChainOfThoughtProps) {
  const [displayedSteps, setDisplayedSteps] = useState<ThoughtStep[]>([]);

  useEffect(() => {
    if (steps.length === 0) {
      setDisplayedSteps([]);
      return;
    }

    // Show all steps up to the current one
    const currentSteps = steps.filter((_, idx) => idx < steps.length);
    setDisplayedSteps(currentSteps);
  }, [steps]);

  if (!isActive || displayedSteps.length === 0) {
    return null;
  }

  return (
    <Card className="border-primary/20 bg-primary/5">
      <CardContent className="p-4">
        <div className="space-y-3">
          {displayedSteps.map((step, idx) => (
            <div
              key={step.id || idx}
              className={cn(
                "flex items-start gap-3 transition-all duration-300",
                step.completed && "opacity-75"
              )}
            >
              <div className="flex-shrink-0 mt-0.5">
                {step.completed ? (
                  <CheckCircle2 className="h-4 w-4 text-primary" />
                ) : (
                  <Circle className="h-4 w-4 text-primary animate-pulse" />
                )}
              </div>
              <p
                className={cn(
                  "text-sm flex-1",
                  step.completed ? "text-muted-foreground" : "text-foreground"
                )}
              >
                {step.text}
              </p>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

