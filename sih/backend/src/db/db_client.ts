import pg from 'pg';
import { config } from '../config.js';

const { Pool } = pg;

// ══════════════════════════════════════════════════════════════════════════════
// Types
// ══════════════════════════════════════════════════════════════════════════════

export interface DatabaseConfig {
  connectionString: string;
  maxConnections?: number;
  idleTimeoutMs?: number;
  connectionTimeoutMs?: number;
  retryAttempts?: number;
  retryDelayMs?: number;
}

export interface QueryResult<T = any> {
  rows: T[];
  rowCount: number;
  command: string;
  oid: number;
  fields: pg.FieldDef[];
}

// ══════════════════════════════════════════════════════════════════════════════
// Database Client
// ══════════════════════════════════════════════════════════════════════════════

export class DatabaseClient {
  private pool: pg.Pool;
  private retryAttempts: number;
  private retryDelayMs: number;
  private isConnecting: boolean = false;
  private connectionPromise: Promise<void> | null = null;

  constructor(dbConfig?: Partial<DatabaseConfig>) {
    const cfg: DatabaseConfig = {
      connectionString: dbConfig?.connectionString ?? config.databaseUrl,
      maxConnections: dbConfig?.maxConnections ?? 20,
      idleTimeoutMs: dbConfig?.idleTimeoutMs ?? 30000,
      connectionTimeoutMs: dbConfig?.connectionTimeoutMs ?? 5000,
      retryAttempts: dbConfig?.retryAttempts ?? 5,
      retryDelayMs: dbConfig?.retryDelayMs ?? 1000,
    };

    this.retryAttempts = cfg.retryAttempts;
    this.retryDelayMs = cfg.retryDelayMs;

    this.pool = new Pool({
      connectionString: cfg.connectionString,
      max: cfg.maxConnections,
      idleTimeoutMillis: cfg.idleTimeoutMs,
      connectionTimeoutMillis: cfg.connectionTimeoutMs,
      // Enable automatic reconnection
      allowExitOnIdle: false,
    });

    // Handle pool errors
    this.pool.on('error', (err) => {
      console.error('[DB] Unexpected pool error:', err.message);
    });

    this.pool.on('connect', () => {
      console.log('[DB] New client connected');
    });

    this.pool.on('remove', () => {
      console.log('[DB] Client removed from pool');
    });
  }

  // ─── Connection Management ─────────────────────────────────────────────────

  /**
   * Initialize database connection with retry logic
   */
  async connect(): Promise<void> {
    if (this.isConnecting) {
      return this.connectionPromise!;
    }

    this.isConnecting = true;
    this.connectionPromise = this._connectWithRetry();

    try {
      await this.connectionPromise;
    } finally {
      this.isConnecting = false;
    }
  }

  private async _connectWithRetry(): Promise<void> {
    for (let attempt = 1; attempt <= this.retryAttempts; attempt++) {
      try {
        const client = await this.pool.connect();
        console.log(`[DB] Connected successfully (attempt ${attempt})`);
        client.release();
        return;
      } catch (err) {
        const error = err as Error;
        console.warn(
          `[DB] Connection attempt ${attempt}/${this.retryAttempts} failed: ${error.message}`
        );

        if (attempt === this.retryAttempts) {
          throw new Error(
            `[DB] Failed to connect after ${this.retryAttempts} attempts: ${error.message}`
          );
        }

        // Exponential backoff
        const delay = this.retryDelayMs * Math.pow(2, attempt - 1);
        console.log(`[DB] Retrying in ${delay}ms...`);
        await this.sleep(delay);
      }
    }
  }

  /**
   * Close all connections in the pool
   */
  async disconnect(): Promise<void> {
    try {
      await this.pool.end();
      console.log('[DB] Pool closed');
    } catch (err) {
      console.error('[DB] Error closing pool:', err);
    }
  }

  /**
   * Check if database is connected
   */
  async isConnected(): Promise<boolean> {
    try {
      const client = await this.pool.connect();
      client.release();
      return true;
    } catch {
      return false;
    }
  }

  // ─── Query Execution with Retry ───────────────────────────────────────────

  /**
   * Execute a query with automatic retry on connection errors
   */
  async query<T = any>(
    text: string,
    params?: any[],
    options?: { retryOnConnectionError?: boolean }
  ): Promise<QueryResult<T>> {
    const retryOnConnectionError = options?.retryOnConnectionError ?? true;
    const maxAttempts = retryOnConnectionError ? this.retryAttempts : 1;

    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      try {
        const result = await this.pool.query<T>(text, params);
        return result;
      } catch (err) {
        const error = err as Error;
        const isConnectionError = this.isConnectionError(error);

        if (isConnectionError && attempt < maxAttempts) {
          console.warn(
            `[DB] Query failed (attempt ${attempt}/${maxAttempts}), retrying: ${error.message}`
          );
          await this.sleep(this.retryDelayMs * attempt);
          continue;
        }

        throw error;
      }
    }

    throw new Error('[DB] Query failed after all retry attempts');
  }

  /**
   * Execute a query within a transaction
   */
  async transaction<T>(
    callback: (client: pg.PoolClient) => Promise<T>
  ): Promise<T> {
    const client = await this.pool.connect();
    
    try {
      await client.query('BEGIN');
      const result = await callback(client);
      await client.query('COMMIT');
      return result;
    } catch (err) {
      await client.query('ROLLBACK');
      throw err;
    } finally {
      client.release();
    }
  }

  /**
   * Execute multiple queries in a batch transaction
   */
  async batchQuery<T>(
    queries: Array<{ text: string; params?: any[] }>
  ): Promise<QueryResult<T>[]> {
    return this.transaction(async (client) => {
      const results: QueryResult<T>[] = [];
      
      for (const query of queries) {
        const result = await client.query<T>(query.text, query.params);
        results.push(result);
      }
      
      return results;
    });
  }

  // ─── Connection Health ─────────────────────────────────────────────────────

  /**
   * Get pool statistics
   */
  getPoolStats(): {
    totalCount: number;
    idleCount: number;
    waitingCount: number;
  } {
    return {
      totalCount: this.pool.totalCount,
      idleCount: this.pool.idleCount,
      waitingCount: this.pool.waitingCount,
    };
  }

  /**
   * Check if error is a connection-related error
   */
  private isConnectionError(err: Error): boolean {
    const connectionErrors = [
      'ECONNREFUSED',
      'ECONNRESET',
      'EPIPE',
      'ETIMEDOUT',
      'connection terminated',
      'connection refused',
      'server closed the connection',
      'Client has encountered a connection error',
    ];

    return connectionErrors.some((pattern) =>
      err.message.toLowerCase().includes(pattern.toLowerCase())
    );
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// Singleton Instance
// ══════════════════════════════════════════════════════════════════════════════

let instance: DatabaseClient | null = null;

export function getDatabaseClient(): DatabaseClient {
  if (!instance) {
    instance = new DatabaseClient();
  }
  return instance;
}

export async function initializeDatabase(): Promise<DatabaseClient> {
  const db = getDatabaseClient();
  await db.connect();
  return db;
}

export async function shutdownDatabase(): Promise<void> {
  if (instance) {
    await instance.disconnect();
    instance = null;
  }
}

export default DatabaseClient;
