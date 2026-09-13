/**
 * Official Osnabrück individual-space occupancy source.
 *
 * The city data platform exposes SensorThings records for individual
 * sensor-equipped accessible parking spaces. This adapter uses the source
 * Thing IDs only to select the pilot corridor; coordinates and occupancy are
 * read from the API on every refresh. There is deliberately no local state
 * override and no manual "taken" endpoint.
 */

export const OSNABRUCK_SOURCE = {
  name: "Osnabrück city data platform — individual parking-space sensors",
  apiBaseUrl: "https://daten-api.osnabrueck.de/v1.1",
  datasetUrl: "https://datenplattform.osnabrueck.de/parkplatzdaten/",
  apiDocumentationUrl: "https://datenplattform.osnabrueck.de/daten-api-osnabrueck/",
  updateNote: "Each status and timestamp is read from the official SensorThings API. No manual or generated occupancy is used.",
} as const;

export const OSNABRUCK_PILOT_THING_IDS = [342, 288, 267] as const;

export type OsnabrueckAvailability = "VACANT" | "OCCUPIED" | "UNKNOWN";

export interface OsnabrueckObservation {
  rawState: string;
  availability: OsnabrueckAvailability;
  phenomenonTime: string;
  resultTime: string | null;
}

export interface OsnabrueckSpot {
  spotId: string;
  sourceThingId: number;
  sourceDatastreamId: number;
  label: string;
  latitude: number;
  longitude: number;
  availability: OsnabrueckAvailability;
  rawState: string;
  observedAt: string | null;
  resultTime: string | null;
  ageSeconds: number | null;
  fresh: boolean;
  active: boolean;
  accessibleSpace: boolean;
  sourceName: string;
  history: OsnabrueckObservation[];
}

export interface OsnabrueckSnapshot {
  fetchedAt: string;
  spots: OsnabrueckSpot[];
}

// The official feed is real, but the pilot must not route on an old reading.
// Six hours is intentionally visible in the UI so its freshness policy is
// inspectable. A reading older than this becomes UNKNOWN and is excluded.
export const MAX_OBSERVATION_AGE_MS = 6 * 60 * 60 * 1000;

interface SensorThingsObservation {
  phenomenonTime?: string;
  resultTime?: string;
  result?: unknown;
}

interface SensorThingsDatastream {
  "@iot.id"?: number;
  name?: string;
  observedArea?: { coordinates?: unknown };
  Observations?: SensorThingsObservation[];
}

interface SensorThingsThing {
  "@iot.id"?: number;
  name?: string;
  properties?: Record<string, unknown>;
  Datastreams?: SensorThingsDatastream[];
}

function sourceUrl(thingId: number): string {
  const expand = "Datastreams($filter=substringof('Belegtstatus',name);$expand=Observations($orderby=phenomenonTime desc;$top=2))";
  return `${OSNABRUCK_SOURCE.apiBaseUrl}/Things(${thingId})?$expand=${encodeURIComponent(expand)}`;
}

async function fetchThing(thingId: number): Promise<SensorThingsThing> {
  const response = await fetch(sourceUrl(thingId), {
    headers: { "User-Agent": "Parking-Truth-Engine/0.1 Osnabrueck sensor pilot" },
    signal: AbortSignal.timeout(15_000),
  });
  if (!response.ok) throw new Error(`Osnabrück source returned HTTP ${response.status} for Thing ${thingId}`);
  return await response.json() as SensorThingsThing;
}

function coordinatesFrom(datastream: SensorThingsDatastream, properties: Record<string, unknown>): [number, number] | null {
  const coordinates = datastream.observedArea?.coordinates;
  if (Array.isArray(coordinates) && coordinates.length >= 2) {
    const longitude = Number(coordinates[0]);
    const latitude = Number(coordinates[1]);
    if (Number.isFinite(latitude) && Number.isFinite(longitude)) return [latitude, longitude];
  }

  // This is only a second representation of the same official Thing record.
  const navigation = typeof properties.navigation === "string" ? properties.navigation : "";
  const match = navigation.match(/q=([-+\d.]+)%2C([-+\d.]+)/i);
  if (match) {
    const latitude = Number(match[1]);
    const longitude = Number(match[2]);
    if (Number.isFinite(latitude) && Number.isFinite(longitude)) return [latitude, longitude];
  }
  return null;
}

function mapAvailability(rawState: string): OsnabrueckAvailability {
  const normalized = rawState.trim().toLowerCase();
  if (normalized === "frei") return "VACANT";
  if (normalized === "belegt") return "OCCUPIED";
  return "UNKNOWN";
}

function latestObservation(observations: SensorThingsObservation[]): OsnabrueckObservation[] {
  return observations
    .filter((observation) => typeof observation.phenomenonTime === "string")
    .map((observation) => ({
      rawState: String(observation.result ?? "unknown"),
      availability: mapAvailability(String(observation.result ?? "unknown")),
      phenomenonTime: observation.phenomenonTime as string,
      resultTime: typeof observation.resultTime === "string" ? observation.resultTime : null,
    }))
    .sort((a, b) => Date.parse(b.phenomenonTime) - Date.parse(a.phenomenonTime));
}

export async function fetchOsnabrueckSnapshot(): Promise<OsnabrueckSnapshot> {
  const things = await Promise.all(OSNABRUCK_PILOT_THING_IDS.map(fetchThing));
  const fetchedAt = new Date().toISOString();
  const spots = things.map((thing, index) => {
    const datastream = thing.Datastreams?.find((candidate) => candidate.Observations?.length);
    if (!datastream || typeof thing["@iot.id"] !== "number" || typeof datastream["@iot.id"] !== "number") {
      throw new Error(`Osnabrück Thing ${OSNABRUCK_PILOT_THING_IDS[index]} has no occupancy datastream`);
    }
    const coordinates = coordinatesFrom(datastream, thing.properties ?? {});
    if (!coordinates) throw new Error(`Osnabrück Thing ${thing["@iot.id"]} has no official coordinates`);

    const history = latestObservation(datastream.Observations ?? []);
    const latest = history[0];
    if (!latest) throw new Error(`Osnabrück Thing ${thing["@iot.id"]} has no official observation`);
    const observedAtMs = Date.parse(latest.phenomenonTime);
    const ageSeconds = Number.isFinite(observedAtMs) ? Math.max(0, Math.round((Date.now() - observedAtMs) / 1000)) : null;
    const fresh = ageSeconds !== null && ageSeconds * 1000 <= MAX_OBSERVATION_AGE_MS;
    const rawAvailability = latest.availability;
    const availability = fresh ? rawAvailability : "UNKNOWN";
    const properties = thing.properties ?? {};
    const active = String(properties.betriebsstatus ?? "").toLowerCase() === "aktiv";
    const accessibleSpace = String(properties.behindertenparkplatz ?? "").toLowerCase() === "ja";

    return {
      spotId: `OSN-${index + 1}`,
      sourceThingId: thing["@iot.id"],
      sourceDatastreamId: datastream["@iot.id"],
      label: thing.name ?? `Official sensor space ${thing["@iot.id"]}`,
      latitude: coordinates[0],
      longitude: coordinates[1],
      availability,
      rawState: latest.rawState,
      observedAt: latest.phenomenonTime,
      resultTime: latest.resultTime,
      ageSeconds,
      fresh,
      active,
      accessibleSpace,
      sourceName: OSNABRUCK_SOURCE.name,
      history,
    } satisfies OsnabrueckSpot;
  });

  return { fetchedAt, spots };
}
