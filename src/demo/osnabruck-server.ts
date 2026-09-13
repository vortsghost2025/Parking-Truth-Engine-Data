/**
 * Isolated Osnabrück real individual-space sensor pilot.
 *
 * Run locally with:
 *   PTE_OSNABRUCK_PORT=8790 node src/demo/osnabruck-server.ts
 *
 * The app's occupancy decisions are made from the official SensorThings feed.
 * There is no endpoint that can manually mark a space taken.
 */

import { readFile } from "node:fs/promises";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  fetchOsnabrueckSnapshot,
  MAX_OBSERVATION_AGE_MS,
  OSNABRUCK_PILOT_THING_IDS,
  OSNABRUCK_SOURCE,
  type OsnabrueckSnapshot,
  type OsnabrueckSpot,
} from "./osnabruck-source.ts";

const PORT = Number(process.env.PTE_OSNABRUCK_PORT ?? 8790);
const HOST = process.env.PTE_OSNABRUCK_HOST ?? "127.0.0.1";
const REFRESH_INTERVAL_MS = 60 * 1000;
const PILOT_CENTER = { latitude: 52.274, longitude: 8.05 } as const;
const PILOT_RADIUS_METERS = 2_000;

type SelectionOutcome =
  | "TARGET_SELECTED"
  | "NO_LIVE_SPACE_AVAILABLE"
  | "COVERAGE_UNAVAILABLE"
  | "LIVE_FEED_UNAVAILABLE"
  | "NO_DESTINATION";

interface Destination {
  latitude: number;
  longitude: number;
  label: string;
}

interface PilotState {
  snapshot: OsnabrueckSnapshot | null;
  destination: Destination | null;
  error: string | null;
}

const state: PilotState = { snapshot: null, destination: null, error: null };

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    "Access-Control-Allow-Origin": "*",
  });
  res.end(JSON.stringify(body));
}

function sendHtml(res: ServerResponse, html: string): void {
  res.writeHead(200, { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" });
  res.end(html);
}

function distanceMeters(aLat: number, aLon: number, bLat: number, bLon: number): number {
  const radius = 6_371_000;
  const radians = Math.PI / 180;
  const dLat = (bLat - aLat) * radians;
  const dLon = (bLon - aLon) * radians;
  const haversine = Math.sin(dLat / 2) ** 2
    + Math.cos(aLat * radians) * Math.cos(bLat * radians) * Math.sin(dLon / 2) ** 2;
  return 2 * radius * Math.asin(Math.min(1, Math.sqrt(haversine)));
}

function validCoordinate(value: unknown, minimum: number, maximum: number): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= minimum && value <= maximum;
}

function inPilotArea(destination: Destination): boolean {
  return distanceMeters(destination.latitude, destination.longitude, PILOT_CENTER.latitude, PILOT_CENTER.longitude) <= PILOT_RADIUS_METERS;
}

function snapshotConnected(snapshot: OsnabrueckSnapshot | null): snapshot is OsnabrueckSnapshot {
  return Boolean(snapshot && snapshot.spots.length === OSNABRUCK_PILOT_THING_IDS.length);
}

function rankSpots(destination: Destination, spots: OsnabrueckSpot[]) {
  return spots
    .filter((spot) => spot.active && spot.accessibleSpace && spot.fresh && spot.availability === "VACANT")
    .map((spot) => ({ ...spot, distanceMeters: Math.round(distanceMeters(destination.latitude, destination.longitude, spot.latitude, spot.longitude)) }))
    .sort((a, b) => a.distanceMeters - b.distanceMeters);
}

function sourceView() {
  const spots = state.snapshot?.spots ?? [];
  const newestObservedAt = spots
    .map((spot) => spot.observedAt)
    .filter((value): value is string => Boolean(value))
    .sort((a, b) => Date.parse(b) - Date.parse(a))[0] ?? null;
  return {
    connected: snapshotConnected(state.snapshot),
    name: OSNABRUCK_SOURCE.name,
    apiBaseUrl: OSNABRUCK_SOURCE.apiBaseUrl,
    datasetUrl: OSNABRUCK_SOURCE.datasetUrl,
    apiDocumentationUrl: OSNABRUCK_SOURCE.apiDocumentationUrl,
    updateNote: OSNABRUCK_SOURCE.updateNote,
    fetchedAt: state.snapshot?.fetchedAt ?? null,
    newestObservedAt,
    maxObservationAgeSeconds: MAX_OBSERVATION_AGE_MS / 1000,
    pilotThingIds: [...OSNABRUCK_PILOT_THING_IDS],
    error: state.error,
  };
}

function view(): Record<string, unknown> {
  const spots = state.snapshot?.spots ?? [];
  let outcome: SelectionOutcome = "NO_DESTINATION";
  let ranked: Array<OsnabrueckSpot & { distanceMeters: number }> = [];
  let target: (OsnabrueckSpot & { distanceMeters: number }) | null = null;

  if (!snapshotConnected(state.snapshot)) {
    outcome = "LIVE_FEED_UNAVAILABLE";
  } else if (state.destination) {
    if (!inPilotArea(state.destination)) {
      outcome = "COVERAGE_UNAVAILABLE";
    } else {
      ranked = rankSpots(state.destination, spots);
      target = ranked[0] ?? null;
      outcome = target ? "TARGET_SELECTED" : "NO_LIVE_SPACE_AVAILABLE";
    }
  }

  return {
    outcome,
    destination: state.destination,
    spots,
    ranked,
    target,
    source: sourceView(),
  };
}

async function refreshSnapshot(): Promise<void> {
  try {
    state.snapshot = await fetchOsnabrueckSnapshot();
    state.error = null;
  } catch (error) {
    state.error = error instanceof Error ? error.message : "Osnabrück official feed unavailable";
  }
}

async function readBody(req: IncomingMessage): Promise<string> {
  let raw = "";
  for await (const chunk of req) raw += chunk as string;
  return raw;
}

function parsePoint(value: string | null): [number, number] | null {
  const numbers = value?.split(",").map(Number) ?? [];
  if (numbers.length !== 2 || !validCoordinate(numbers[0], -90, 90) || !validCoordinate(numbers[1], -180, 180)) return null;
  return [numbers[0], numbers[1]];
}

async function geocode(query: string): Promise<unknown> {
  const url = new URL("https://nominatim.openstreetmap.org/search");
  url.searchParams.set("format", "jsonv2");
  url.searchParams.set("limit", "1");
  url.searchParams.set("countrycodes", "de");
  url.searchParams.set("q", query);
  const response = await fetch(url, {
    headers: {
      "User-Agent": "Parking-Truth-Engine/0.1 Osnabrueck sensor pilot (contact via source project)",
      Accept: "application/json",
    },
    signal: AbortSignal.timeout(15_000),
  });
  if (!response.ok) throw new Error(`geocoder returned HTTP ${response.status}`);
  const results = await response.json() as Array<{ lat?: string; lon?: string; display_name?: string }>;
  const first = results[0];
  const latitude = Number(first?.lat);
  const longitude = Number(first?.lon);
  if (!first || !Number.isFinite(latitude) || !Number.isFinite(longitude)) return null;
  return { latitude, longitude, label: first.display_name ?? query, source: "OpenStreetMap Nominatim" };
}

async function roadRoute(from: [number, number], to: [number, number]): Promise<unknown> {
  const url = `https://router.project-osrm.org/route/v1/driving/${from[1]},${from[0]};${to[1]},${to[0]}?overview=full&geometries=geojson&steps=false`;
  const response = await fetch(url, {
    headers: { "User-Agent": "Parking-Truth-Engine/0.1 Osnabrueck sensor pilot" },
    signal: AbortSignal.timeout(15_000),
  });
  if (!response.ok) throw new Error(`road router returned HTTP ${response.status}`);
  const result = await response.json() as {
    code?: string;
    routes?: Array<{ distance?: number; duration?: number; geometry?: { coordinates?: unknown } }>;
  };
  const route = result.routes?.[0];
  if (result.code !== "Ok" || !route || !Array.isArray(route.geometry?.coordinates)) throw new Error("road router returned no route");
  return {
    source: "OpenStreetMap road network via OSRM",
    distanceMeters: Math.round(route.distance ?? 0),
    durationSeconds: Math.max(1, Math.round(route.duration ?? 0)),
    coordinates: route.geometry.coordinates,
  };
}

const server = createServer(async (req, res) => {
  const requestUrl = new URL(req.url ?? "/", `http://${HOST}:${PORT}`);

  if (req.method === "GET" && (requestUrl.pathname === "/" || requestUrl.pathname === "/osnabrueck")) {
    const destinationQuery = requestUrl.searchParams.get("destination")?.trim();
    if (destinationQuery) {
      try {
        const result = await geocode(destinationQuery) as { latitude?: number; longitude?: number; label?: string } | null;
        if (result && validCoordinate(result.latitude, -90, 90) && validCoordinate(result.longitude, -180, 180)) {
          state.destination = { latitude: result.latitude, longitude: result.longitude, label: result.label ?? destinationQuery };
        }
      } catch (error) {
        state.error = error instanceof Error ? error.message : "address lookup unavailable";
      }
    }
    if (!state.snapshot || Date.now() - Date.parse(state.snapshot.fetchedAt) > REFRESH_INTERVAL_MS) await refreshSnapshot();
    const template = await readFile(join(dirname(fileURLToPath(import.meta.url)), "osnabruck.html"), "utf8");
    const serializedState = JSON.stringify(view()).replace(/</g, "\\u003c");
    sendHtml(res, template.replace("window.__INITIAL_STATE__ = null;", `window.__INITIAL_STATE__ = ${serializedState};`));
    return;
  }

  if (req.method === "GET" && requestUrl.pathname === "/health") {
    sendJson(res, 200, { ok: true, pilot: "osnabrueck-individual-sensors" });
    return;
  }

  if (req.method === "GET" && requestUrl.pathname === "/feed/state") {
    if (!state.snapshot || Date.now() - Date.parse(state.snapshot.fetchedAt) > REFRESH_INTERVAL_MS) await refreshSnapshot();
    sendJson(res, 200, view());
    return;
  }

  if (req.method === "GET" && requestUrl.pathname === "/find/address") {
    const query = requestUrl.searchParams.get("q")?.trim() ?? "";
    if (query.length < 3) {
      sendJson(res, 400, { error: "Enter at least three characters" });
      return;
    }
    try {
      const result = await geocode(query);
      sendJson(res, 200, result ?? { error: "No real address result found" });
    } catch (error) {
      sendJson(res, 502, { error: error instanceof Error ? error.message : "geocoder unavailable" });
    }
    return;
  }

  if (req.method === "POST" && requestUrl.pathname === "/feed/select") {
    let body: { latitude?: number; longitude?: number; label?: string };
    try {
      body = JSON.parse(await readBody(req)) as typeof body;
    } catch {
      sendJson(res, 400, { error: "invalid JSON" });
      return;
    }
    if (!validCoordinate(body.latitude, -90, 90) || !validCoordinate(body.longitude, -180, 180)) {
      sendJson(res, 400, { error: "latitude and longitude are required" });
      return;
    }
    state.destination = {
      latitude: body.latitude,
      longitude: body.longitude,
      label: body.label?.trim() || "Selected destination",
    };
    if (!state.snapshot || Date.now() - Date.parse(state.snapshot.fetchedAt) > REFRESH_INTERVAL_MS) await refreshSnapshot();
    sendJson(res, 200, view());
    return;
  }

  if (req.method === "GET" && requestUrl.pathname === "/routing") {
    const from = parsePoint(requestUrl.searchParams.get("from"));
    const to = parsePoint(requestUrl.searchParams.get("to"));
    if (!from || !to) {
      sendJson(res, 400, { error: "from and to must be latitude,longitude pairs" });
      return;
    }
    try {
      sendJson(res, 200, await roadRoute(from, to));
    } catch (error) {
      sendJson(res, 502, { error: error instanceof Error ? error.message : "road route unavailable" });
    }
    return;
  }

  sendJson(res, 404, { error: "not found" });
});

server.listen(PORT, HOST, () => {
  console.log("Osnabrück official individual-space sensor pilot");
  console.log(`Open http://${HOST}:${PORT}/osnabrueck`);
  void refreshSnapshot();
});
