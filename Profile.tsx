import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Flight } from "@/types/chat";
import { Plane, Clock, Briefcase, Calendar, AlertCircle } from "lucide-react";
import { format, parse } from "date-fns";

interface FlightCardProps {
  flight: Flight;
}

export function FlightCard({ flight }: FlightCardProps) {
  return (
    <Card className="min-h-[200px]">
      <CardHeader>
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2">
            <div className="h-10 w-10 rounded bg-muted flex items-center justify-center">
              <Plane className="h-5 w-5" />
            </div>
            <div>
              <CardTitle className="text-lg">{flight.airline}</CardTitle>
              <p className="text-sm text-muted-foreground">{flight.flightNumber}</p>
              {flight.date && (
                <div className="flex items-center gap-1 mt-1">
                  <Calendar className="h-3 w-3 text-muted-foreground" />
                  <p className="text-sm font-bold">
                    {format(parse(flight.date, "yyyy-MM-dd", new Date()), "MMM d, yyyy")}
                  </p>
                </div>
              )}
            </div>
          </div>
          <div className="text-right">
            <div className="flex flex-col items-end">
              <p className="text-2xl font-bold">{flight.currency} {flight.price}</p>
              <p className="text-xs text-muted-foreground mt-0.5">Est. price</p>
            </div>
            <Badge variant="outline" className="mt-1">{flight.cabin}</Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {flight.dateTooFarAhead && (
          <Alert variant="default" className="bg-amber-50 dark:bg-amber-950/20 border-amber-200 dark:border-amber-800">
            <AlertCircle className="h-4 w-4 text-amber-600 dark:text-amber-400" />
            <AlertDescription className="text-sm text-amber-800 dark:text-amber-200">
              This date is more than 330 days in advance. Google Flights typically only shows flights up to 330 days ahead. 
              Click below to search manually on Google Flights.
            </AlertDescription>
          </Alert>
        )}
        <div className="flex items-center justify-between">
          <div>
            <p className="text-2xl font-semibold">{flight.departAirport}</p>
            <p className="text-sm text-muted-foreground">
              {flight.departTime && flight.departTime !== "Unknown" ? flight.departTime : "Time TBD"}
            </p>
          </div>
          <div className="flex flex-col items-center px-4">
            <Clock className="h-4 w-4 text-muted-foreground mb-1" />
            <p className="text-xs text-muted-foreground">
              {flight.duration && flight.duration !== "Unknown" ? flight.duration : "Duration TBD"}
            </p>
            <div className="h-[2px] w-24 bg-border my-1" />
            <p className="text-xs text-muted-foreground">
              {flight.stops === 0 ? "Nonstop" : `${flight.stops} stop${flight.stops > 1 ? "s" : ""}`}
            </p>
          </div>
          <div className="text-right">
            <p className="text-2xl font-semibold">{flight.arriveAirport}</p>
            <p className="text-sm text-muted-foreground">
              {flight.arriveTime && flight.arriveTime !== "Unknown" ? flight.arriveTime : "Time TBD"}
            </p>
          </div>
        </div>
        {flight.baggage && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Briefcase className="h-4 w-4" />
            <span>{flight.baggage}</span>
          </div>
        )}
      </CardContent>
      <CardFooter className="flex flex-col gap-2">
        <Button 
          className="flex-1 w-full" 
          onClick={() => {
            const url = flight.bookingLink || `https://www.google.com/travel/flights?q=Flights+from+${flight.departAirport}+to+${flight.arriveAirport}`;
            window.open(url, "_blank");
          }}
        >
          View on Google Flights
        </Button>
        <p className="text-xs text-muted-foreground text-center">
          Prices are estimates and may vary. Verify final price on Google Flights.
        </p>
      </CardFooter>
    </Card>
  );
}
