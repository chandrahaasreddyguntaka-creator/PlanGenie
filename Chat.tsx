import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Hotel } from "@/types/chat";
import { Hotel as HotelIcon, Star, MapPin, Phone } from "lucide-react";

interface HotelCardProps {
  hotel: Hotel;
}

export function HotelCard({ hotel }: HotelCardProps) {
  return (
    <Card className="min-h-[250px]">
      <CardHeader>
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2">
            <div className="h-10 w-10 rounded bg-muted flex items-center justify-center">
              <HotelIcon className="h-5 w-5" />
            </div>
            <div>
              <CardTitle className="text-lg">{hotel.name}</CardTitle>
              <div className="flex items-center gap-1 mt-1">
                {Array.from({ length: hotel.stars }).map((_, i) => (
                  <Star key={i} className="h-3 w-3 fill-primary text-primary" />
                ))}
              </div>
            </div>
          </div>
          <div className="text-right">
            {hotel.nightlyPrice > 0 && (
              <div className="space-y-1">
                <div className="text-lg font-semibold">
                  {hotel.currency} {hotel.nightlyPrice.toFixed(0)}
                  <span className="text-sm font-normal text-muted-foreground">/night</span>
                </div>
                {hotel.totalPrice > 0 && hotel.totalPrice !== hotel.nightlyPrice && (
                  <div className="text-sm text-muted-foreground">
                    Total: {hotel.currency} {hotel.totalPrice.toFixed(0)}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <MapPin className="h-4 w-4" />
          <span>{hotel.neighborhood}</span>
        </div>
        {hotel.refundable && (
          <Badge variant="secondary">Refundable</Badge>
        )}
        <div className="flex flex-wrap gap-2">
          {hotel.amenities.map((amenity) => (
            <Badge key={amenity} variant="outline" className="text-xs">
              {amenity}
            </Badge>
          ))}
        </div>
      </CardContent>
      <CardFooter className="flex flex-col gap-2">
        <div className="flex gap-2 w-full">
          <Button className="flex-1" onClick={() => hotel.bookingLink && window.open(hotel.bookingLink, "_blank")}>
            View on Provider
          </Button>
          {hotel.phone && (
            <Button variant="outline" size="icon" onClick={() => window.location.href = `tel:${hotel.phone}`}>
              <Phone className="h-4 w-4" />
            </Button>
          )}
        </div>
        {!hotel.bookingLink && (
          <p className="text-xs text-muted-foreground">
            No direct link from source; try provider search.
          </p>
        )}
      </CardFooter>
    </Card>
  );
}
