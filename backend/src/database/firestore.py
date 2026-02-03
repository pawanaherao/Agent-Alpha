from google.cloud import firestore
from src.core.config import settings
import logging

logger = logging.getLogger(__name__)

class FirestoreClient:
    """
    Wrapper for Google Cloud Firestore.
    Used for real-time data and audit logs.
    """
    def __init__(self):
        self.client = None

    def connect(self):
        """Initialize Firestore client."""
        try:
            # In local mode, this connects to emulator via env var FIRESTORE_EMULATOR_HOST
            self.client = firestore.AsyncClient(project=settings.GCP_PROJECT)
            logger.info("Connected to Firestore")
        except Exception as e:
            logger.error(f"Failed to connect to Firestore: {e}")
            raise

    async def get_document(self, collection: str, doc_id: str):
        """Get a document."""
        doc_ref = self.client.collection(collection).document(doc_id)
        doc = await doc_ref.get()
        return doc.to_dict() if doc.exists else None

    async def set_document(self, collection: str, doc_id: str, data: dict):
        """Set/Update a document."""
        doc_ref = self.client.collection(collection).document(doc_id)
        await doc_ref.set(data)

    async def add_document(self, collection: str, data: dict):
        """Add a document with auto-generated ID."""
        await self.client.collection(collection).add(data)

db_firestore = FirestoreClient()
