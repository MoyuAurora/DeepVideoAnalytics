from __future__ import unicode_literals
import os, json, gzip, sys, shutil, zipfile, uuid, hashlib

sys.path.append(os.path.join(os.path.dirname(__file__),
                             "../../client/"))  # This ensures that the constants are same between client and server
from django.db import models
from django.contrib.auth.models import User
from django.contrib.postgres.fields import JSONField
from django.conf import settings
from django.utils import timezone
from dvaclient import constants
from . import fs
from PIL import Image

try:
    import numpy as np
except ImportError:
    pass
from uuid import UUID
from json import JSONEncoder

JSONEncoder_old = JSONEncoder.default


def JSONEncoder_new(self, o):
    if isinstance(o, UUID): return str(o)
    return JSONEncoder_old(self, o)


JSONEncoder.default = JSONEncoder_new


class Worker(models.Model):
    queue_name = models.CharField(max_length=500, default="")
    host = models.CharField(max_length=500, default="")
    pid = models.IntegerField()
    alive = models.BooleanField(default=True)
    last_ping = models.DateTimeField('date last ping', null=True)
    created = models.DateTimeField('date created', auto_now_add=True)


class DVAPQL(models.Model):
    SCHEDULE = constants.SCHEDULE
    PROCESS = constants.PROCESS
    QUERY = constants.QUERY
    TYPE_CHOICES = ((SCHEDULE, 'Schedule'), (PROCESS, 'Process'), (QUERY, 'Query'))
    process_type = models.CharField(max_length=1, choices=TYPE_CHOICES, default=QUERY, )
    created = models.DateTimeField('date created', auto_now_add=True)
    user = models.ForeignKey(User, null=True, related_name="submitter")
    script = JSONField(blank=True, null=True)
    results_metadata = models.TextField(default="")
    results_available = models.BooleanField(default=False)
    completed = models.BooleanField(default=False)
    failed = models.BooleanField(default=False)
    error_message = models.TextField(default="", blank=True, null=True)
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)


class TrainingSet(models.Model):
    DETECTION = constants.DETECTION
    INDEXING = constants.INDEXING
    TRAINAPPROX = constants.TRAINAPPROX
    CLASSIFICATION = constants.CLASSIFICATION
    IMAGES = constants.IMAGES
    VIDEOS = constants.VIDEOS
    INDEX = constants.INDEX
    INSTANCE_TYPES = (
        (IMAGES, 'images'),
        (INDEX, 'index'),
        (VIDEOS, 'videos'),
    )
    TRAIN_TASK_TYPES = (
        (DETECTION, 'Detection'),
        (INDEXING, 'Indexing'),
        (TRAINAPPROX, 'Approximation'),
        (CLASSIFICATION, 'Classification')
    )
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    source_filters = JSONField(blank=True, null=True)
    training_task_type = models.CharField(max_length=1, choices=TRAIN_TASK_TYPES, db_index=True, default=DETECTION)
    instance_type = models.CharField(max_length=1, choices=INSTANCE_TYPES, db_index=True, default=IMAGES)
    count = models.IntegerField(null=True)
    name = models.CharField(max_length=500, default="")
    files = JSONField(blank=True, null=True)
    built = models.BooleanField(default=False)
    created = models.DateTimeField('date created', auto_now_add=True)


class Video(models.Model):
    id = models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)
    name = models.CharField(max_length=500, default="")
    length_in_seconds = models.IntegerField(default=0)
    height = models.IntegerField(default=0)
    width = models.IntegerField(default=0)
    metadata = models.TextField(default="")
    frames = models.IntegerField(default=0)
    created = models.DateTimeField('date created', auto_now_add=True)
    description = models.TextField(default="")
    uploaded = models.BooleanField(default=False)
    dataset = models.BooleanField(default=False)
    uploader = models.ForeignKey(User, null=True)
    segments = models.IntegerField(default=0)
    stream = models.BooleanField(default=False)
    url = models.TextField(default="")
    parent_process = models.ForeignKey(DVAPQL, null=True)

    def __unicode__(self):
        return u'{}'.format(self.name)

    def path(self, media_root=None):
        if not (media_root is None):
            return "{}/{}/video/{}.mp4".format(media_root, self.pk, self.pk)
        else:
            return "{}/{}/video/{}.mp4".format(settings.MEDIA_ROOT, self.pk, self.pk)

    def segments_dir(self, media_root=None):
        if not (media_root is None):
            return "{}/{}/segments/".format(media_root, self.pk, self.pk)
        else:
            return "{}/{}/segments/".format(settings.MEDIA_ROOT, self.pk, self.pk)

    def get_frame_list(self, media_root=None):
        if media_root is None:
            media_root = settings.MEDIA_ROOT
        framelist_path = "{}/{}/framelist".format(media_root, self.pk)
        if os.path.isfile('{}.json'.format(framelist_path)):
            return json.load(file('{}.json'.format(framelist_path)))
        elif os.path.isfile('{}.gz'.format(framelist_path)):
            return json.load(gzip.GzipFile('{}.gz'.format(framelist_path)))
        else:
            raise ValueError("Frame list could not be found at {}".format(framelist_path))

    def create_directory(self, create_subdirs=True):
        d = '{}/{}'.format(settings.MEDIA_ROOT, self.pk)
        if not os.path.exists(d):
            try:
                os.mkdir(d)
            except OSError:
                pass
        if create_subdirs:
            for s in ['video', 'frames', 'segments', 'indexes', 'regions', 'transforms', 'audio']:
                d = '{}/{}/{}/'.format(settings.MEDIA_ROOT, self.pk, s)
                if not os.path.exists(d):
                    try:
                        os.mkdir(d)
                    except OSError:
                        pass


class TEvent(models.Model):
    started = models.BooleanField(default=False)
    completed = models.BooleanField(default=False)
    errored = models.BooleanField(default=False)
    worker = models.ForeignKey(Worker, null=True)
    error_message = models.TextField(default="")
    video = models.ForeignKey(Video, null=True)
    training_set = models.ForeignKey(TrainingSet, null=True)
    operation = models.CharField(max_length=100, default="")
    queue = models.CharField(max_length=100, default="")
    created = models.DateTimeField('date created', auto_now_add=True)
    start_ts = models.DateTimeField('date started', null=True)
    duration = models.FloatField(default=-1)
    arguments = JSONField(blank=True, null=True)
    task_id = models.TextField(null=True)
    parent = models.ForeignKey('self', null=True)
    parent_process = models.ForeignKey(DVAPQL, null=True)
    imported = models.BooleanField(default=False)
    task_group_id = models.IntegerField(default=-1)


class TrainedModel(models.Model):
    """
    A model Model
    """
    TENSORFLOW = constants.TENSORFLOW
    CAFFE = constants.CAFFE
    PYTORCH = constants.PYTORCH
    OPENCV = constants.OPENCV
    MXNET = constants.MXNET
    INDEXER = constants.INDEXER
    APPROXIMATOR = constants.APPROXIMATOR
    DETECTOR = constants.DETECTOR
    ANALYZER = constants.ANALYZER
    SEGMENTER = constants.SEGMENTER
    YOLO = constants.YOLO
    TFD = constants.TFD
    DETECTOR_TYPES = (
        (TFD, 'Tensorflow'),
        (YOLO, 'YOLO V2'),
    )
    MODES = (
        (TENSORFLOW, 'Tensorflow'),
        (CAFFE, 'Caffe'),
        (PYTORCH, 'Pytorch'),
        (OPENCV, 'OpenCV'),
        (MXNET, 'MXNet'),
    )
    MTYPE = (
        (APPROXIMATOR, 'Approximator'),
        (INDEXER, 'Indexer'),
        (DETECTOR, 'Detector'),
        (ANALYZER, 'Analyzer'),
        (SEGMENTER, 'Segmenter'),
    )
    detector_type = models.CharField(max_length=1, choices=DETECTOR_TYPES, db_index=True, null=True)
    mode = models.CharField(max_length=1, choices=MODES, db_index=True, default=TENSORFLOW)
    model_type = models.CharField(max_length=1, choices=MTYPE, db_index=True, default=INDEXER)
    name = models.CharField(max_length=100)
    algorithm = models.CharField(max_length=100, default="")
    shasum = models.CharField(max_length=40, null=True, unique=True)
    model_filename = models.CharField(max_length=200, default="", null=True)
    created = models.DateTimeField('date created', auto_now_add=True)
    arguments = JSONField(null=True, blank=True)
    event = models.ForeignKey(TEvent)
    trained = models.BooleanField(default=False)
    training_set = models.ForeignKey(TrainingSet, null=True)
    url = models.CharField(max_length=200, default="")
    files = JSONField(null=True, blank=True)
    produces_labels = models.BooleanField(default=False)
    produces_json = models.BooleanField(default=False)
    produces_text = models.BooleanField(default=False)
    # Following allows us to have a hierarchy of models (E.g. inception pretrained -> inception fine tuned)
    parent = models.ForeignKey('self', null=True)
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    def create_directory(self):
        if not os.path.isdir('{}/models/'.format(settings.MEDIA_ROOT)):
            try:
                os.mkdir('{}/models/'.format(settings.MEDIA_ROOT))
            except:
                pass
        try:
            os.mkdir('{}/models/{}'.format(settings.MEDIA_ROOT, self.uuid))
        except:
            pass

    def get_model_path(self, root_dir=None):
        if root_dir is None:
            root_dir = settings.MEDIA_ROOT
        if self.model_filename:
            return "{}/models/{}/{}".format(root_dir, self.uuid, self.model_filename)
        elif self.files:
            return "{}/models/{}/{}".format(root_dir, self.uuid, self.files[0]['filename'])
        else:
            return None

    def upload(self):
        for m in self.files:
            if settings.ENABLE_CLOUDFS and sys.platform != 'darwin':
                fs.upload_file_to_remote("/models/{}/{}".format(self.uuid, m['filename']))

    def download(self):
        root_dir = settings.MEDIA_ROOT
        model_type_dir = "{}/models/".format(root_dir)
        if not os.path.isdir(model_type_dir):
            os.mkdir(model_type_dir)
        model_dir = "{}/models/{}".format(root_dir, self.uuid)
        if not os.path.isdir(model_dir):
            try:
                os.mkdir(model_dir)
            except:
                pass
        shasums = []
        for m in self.files:
            dlpath = "{}/{}".format(model_dir, m['filename'])
            if m['url'].startswith('/'):
                shutil.copy(m['url'], dlpath)
            else:
                fs.get_path_to_file(m['url'], dlpath)
            shasums.append(str(hashlib.sha1(file(dlpath).read()).hexdigest()))
        if self.shasum is None:
            if len(shasums) == 1:
                self.shasum = shasums[0]
            else:
                self.shasum = str(hashlib.sha1(''.join(sorted(shasums))).hexdigest())
            self.save()
        self.upload()
        if self.model_type == TrainedModel.DETECTOR and self.detector_type == TrainedModel.YOLO:
            source_zip = "{}/models/{}/model.zip".format(settings.MEDIA_ROOT, self.uuid)
            zipf = zipfile.ZipFile(source_zip, 'r')
            zipf.extractall("{}/models/{}/".format(settings.MEDIA_ROOT, self.uuid))
            zipf.close()
            os.remove(source_zip)
            self.save()
        elif self.model_type == self.INDEXER:
            if settings.ENABLE_FAISS:
                dr, dcreated = Retriever.objects.get_or_create(name=self.name, source_filters={},
                                                               algorithm=Retriever.FAISS,
                                                               indexer_shasum=self.shasum)
            else:
                dr, dcreated = Retriever.objects.get_or_create(name=self.name, source_filters={},
                                                               algorithm=Retriever.EXACT,
                                                               indexer_shasum=self.shasum)
            if dcreated:
                dr.last_built = timezone.now()
                dr.save()
        elif self.model_type == self.APPROXIMATOR:
            algo = Retriever.LOPQ if self.algorithm == 'LOPQ' else Retriever.EXACT
            dr, dcreated = Retriever.objects.get_or_create(name=self.name,
                                                           source_filters={},
                                                           algorithm=algo,
                                                           approximator_shasum=self.shasum,
                                                           indexer_shasum=self.arguments['indexer_shasum'])
            if dcreated:
                dr.last_built = timezone.now()
                dr.save()

    def ensure(self):
        for m in self.files:
            dlpath = "{}/models/{}/{}".format(settings.MEDIA_ROOT, self.uuid, m['filename'])
            if not os.path.isfile(dlpath):
                fs.ensure("/models/{}/{}".format(self.uuid, m['filename']))


class Retriever(models.Model):
    """
    Here Exact is an L2 Flat retriever
    """
    EXACT = 'E'
    LOPQ = 'L'
    FAISS = 'F'
    MODES = (
        (LOPQ, 'LOPQ'),
        (EXACT, 'Exact'),
        (FAISS, 'FAISS'),
    )
    algorithm = models.CharField(max_length=1, choices=MODES, db_index=True, default=EXACT)
    name = models.CharField(max_length=200, default="")
    indexer_shasum = models.CharField(max_length=40, null=True)
    approximator_shasum = models.CharField(max_length=40, null=True)
    source_filters = JSONField()
    created = models.DateTimeField('date created', auto_now_add=True)


class Frame(models.Model):
    video = models.ForeignKey(Video)
    event = models.ForeignKey(TEvent)
    frame_index = models.IntegerField()
    name = models.CharField(max_length=200, null=True)
    h = models.IntegerField(default=0)
    w = models.IntegerField(default=0)
    t = models.FloatField(null=True)  # time in seconds for keyframes
    keyframe = models.BooleanField(default=False)  # is this a key frame for a video?
    segment_index = models.IntegerField(null=True)

    class Meta:
        unique_together = (("video", "frame_index"),)

    def __unicode__(self):
        return u'{}:{}'.format(self.video_id, self.frame_index)

    def path(self, media_root=None):
        if not (media_root is None):
            return "{}/{}/frames/{}.jpg".format(media_root, self.video_id, self.frame_index)
        else:
            return "{}/{}/frames/{}.jpg".format(settings.MEDIA_ROOT, self.video_id, self.frame_index)

    def original_path(self):
        return self.name

    def global_path(self):
        if self.video.dataset:
            if self.name and not self.name.startswith('/'):
                return self.name
            else:
                return "{}/{}".format(self.video.url, self.name)
        else:
            return "{}::{}".format(self.video.url, self.frame_index)


class Segment(models.Model):
    """
    A video segment useful for parallel dense decoding+processing as well as streaming
    """
    video = models.ForeignKey(Video)
    segment_index = models.IntegerField()
    start_time = models.FloatField(default=0.0)
    end_time = models.FloatField(default=0.0)
    event = models.ForeignKey(TEvent)
    metadata = models.TextField(default="{}")
    frame_count = models.IntegerField(default=0)
    start_index = models.IntegerField(default=0)
    framelist = JSONField(blank=True, null=True)
    start_frame = models.ForeignKey(Frame, null=True, related_name="segment_start")
    end_frame = models.ForeignKey(Frame, null=True, related_name="segment_end")

    class Meta:
        unique_together = (("video", "segment_index"),)

    def __unicode__(self):
        return u'{}:{}'.format(self.video_id, self.segment_index)

    def path(self, media_root=None):
        if not (media_root is None):
            return "{}/{}/segments/{}.mp4".format(media_root, self.video_id, self.segment_index)
        else:
            return "{}/{}/segments/{}.mp4".format(settings.MEDIA_ROOT, self.video_id, self.segment_index)


class Region(models.Model):
    """
    Any 2D region over an image.
    Detections & Transforms have an associated image data.
    """
    ANNOTATION = constants.ANNOTATION
    DETECTION = constants.DETECTION
    SEGMENTATION = constants.SEGMENTATION
    TRANSFORM = constants.TRANSFORM
    POLYGON = constants.POLYGON
    REGION_TYPES = (
        (ANNOTATION, 'Annotation'),
        (DETECTION, 'Detection'),
        (POLYGON, 'Polygon'),
        (SEGMENTATION, 'Segmentation'),
        (TRANSFORM, 'Transform'),
    )
    region_type = models.CharField(max_length=1, choices=REGION_TYPES, db_index=True)
    video = models.ForeignKey(Video)
    user = models.ForeignKey(User, null=True)
    frame = models.ForeignKey(Frame, null=True, on_delete=models.SET_NULL)
    event = models.ForeignKey(TEvent)  # TEvent that created this region
    frame_index = models.IntegerField(default=-1)
    segment_index = models.IntegerField(default=-1, null=True)
    text = models.TextField(default="")
    metadata = JSONField(blank=True, null=True)
    full_frame = models.BooleanField(default=False)
    x = models.IntegerField(default=0)
    y = models.IntegerField(default=0)
    h = models.IntegerField(default=0)
    w = models.IntegerField(default=0)
    polygon_points = JSONField(blank=True, null=True)
    created = models.DateTimeField('date created', auto_now_add=True)
    object_name = models.CharField(max_length=100)
    confidence = models.FloatField(default=0.0)
    png = models.BooleanField(default=False)

    def clean(self):
        if self.frame_index == -1 or self.frame_index is None:
            self.frame_index = self.frame.frame_index
        if self.segment_index == -1 or self.segment_index is None:
            self.segment_index = self.frame.segment_index

    def save(self, *args, **kwargs):
        if self.frame_index == -1 or self.frame_index is None:
            self.frame_index = self.frame.frame_index
        if self.segment_index == -1 or self.segment_index is None:
            self.segment_index = self.frame.segment_index
        super(Region, self).save(*args, **kwargs)

    def path(self, media_root=None, temp_root=None):
        if temp_root:
            return "{}/{}_{}.jpg".format(temp_root, self.video_id, self.pk)
        elif not (media_root is None):
            return "{}/{}/regions/{}.jpg".format(media_root, self.video_id, self.pk)
        else:
            return "{}/{}/regions/{}.jpg".format(settings.MEDIA_ROOT, self.video_id, self.pk)

    def frame_path(self, media_root=None):
        if not (media_root is None):
            return "{}/{}/frames/{}.jpg".format(media_root, self.video_id, self.frame_index)
        else:
            return "{}/{}/frames/{}.jpg".format(settings.MEDIA_ROOT, self.video_id, self.frame_index)

    def crop_and_get_region_path(self, images, temp_root):
        bare_path = self.path(media_root="")
        cached_data = fs.get_from_cache(bare_path)
        region_path = self.path(temp_root=temp_root)
        if cached_data:
            with open(region_path, 'wb') as out:
                out.write(cached_data)
        else:
            frame_path = self.frame_path()
            if frame_path not in images:
                images[frame_path] = Image.open(frame_path)
            img2 = images[frame_path].crop((self.x, self.y, self.x + self.w, self.y + self.h))
            img2.save(region_path)
            with open(region_path, 'rb') as fr:
                fs.cache_path(bare_path, payload=fr.read())
        return region_path


class QueryRegion(models.Model):
    """
    Any 2D region over a query image.
    """
    ANNOTATION = constants.ANNOTATION
    DETECTION = constants.DETECTION
    SEGMENTATION = constants.SEGMENTATION
    TRANSFORM = constants.TRANSFORM
    POLYGON = constants.POLYGON
    REGION_TYPES = (
        (ANNOTATION, 'Annotation'),
        (DETECTION, 'Detection'),
        (POLYGON, 'Polygon'),
        (SEGMENTATION, 'Segmentation'),
        (TRANSFORM, 'Transform'),
    )
    region_type = models.CharField(max_length=1, choices=REGION_TYPES, db_index=True)
    query = models.ForeignKey(DVAPQL)
    event = models.ForeignKey(TEvent)  # TEvent that created this region
    text = models.TextField(default="")
    metadata = JSONField(blank=True, null=True)
    full_frame = models.BooleanField(default=False)
    x = models.IntegerField(default=0)
    y = models.IntegerField(default=0)
    h = models.IntegerField(default=0)
    w = models.IntegerField(default=0)
    polygon_points = JSONField(blank=True, null=True)
    created = models.DateTimeField('date created', auto_now_add=True)
    object_name = models.CharField(max_length=100)
    confidence = models.FloatField(default=0.0)
    png = models.BooleanField(default=False)


class QueryResults(models.Model):
    query = models.ForeignKey(DVAPQL)
    retrieval_event = models.ForeignKey(TEvent)
    query_region = models.ForeignKey(QueryRegion, null=True)
    video = models.ForeignKey(Video)
    frame = models.ForeignKey(Frame)
    detection = models.ForeignKey(Region, null=True)
    rank = models.IntegerField()
    algorithm = models.CharField(max_length=100)
    distance = models.FloatField(default=0.0)


class IndexEntries(models.Model):
    video = models.ForeignKey(Video)
    features_file_name = models.CharField(max_length=100)
    entries = JSONField(blank=True, null=True)
    metadata = JSONField(blank=True, null=True)
    algorithm = models.CharField(max_length=100)
    indexer = models.ForeignKey(TrainedModel, null=True)
    indexer_shasum = models.CharField(max_length=40)
    approximator_shasum = models.CharField(max_length=40, null=True)
    detection_name = models.CharField(max_length=100)
    count = models.IntegerField()
    approximate = models.BooleanField(default=False)
    contains_frames = models.BooleanField(default=False)
    contains_detections = models.BooleanField(default=False)
    created = models.DateTimeField('date created', auto_now_add=True)
    event = models.ForeignKey(TEvent)

    def __unicode__(self):
        return "{} in {} index by {}".format(self.detection_name, self.algorithm, self.video.name)

    def npy_path(self, media_root=None):
        if not (media_root is None):
            return "{}/{}/indexes/{}".format(media_root, self.video_id, self.features_file_name)
        else:
            return "{}/{}/indexes/{}".format(settings.MEDIA_ROOT, self.video_id, self.features_file_name)

    def load_index(self, media_root=None):
        if media_root is None:
            media_root = settings.MEDIA_ROOT
        video_dir = "{}/{}".format(media_root, self.video_id)
        if not os.path.isdir(video_dir):
            os.mkdir(video_dir)
        index_dir = "{}/{}/indexes".format(media_root, self.video_id)
        if not os.path.isdir(index_dir):
            os.mkdir(index_dir)
        dirnames = {}
        if self.features_file_name.strip():
            fs.ensure(self.npy_path(media_root=''), dirnames, media_root)
            if self.features_file_name.endswith('.npy'):
                vectors = np.load(self.npy_path(media_root))
            else:
                vectors = self.npy_path(media_root)
        else:
            vectors = None
        return vectors, self.entries


class Tube(models.Model):
    """
    A tube is a collection of sequential frames / regions that track a certain object
    or describe a specific scene
    """
    video = models.ForeignKey(Video, null=True)
    frame_level = models.BooleanField(default=False)
    full_video = models.BooleanField(default=False)
    full_segment = models.BooleanField(default=False)
    start_frame_index = models.IntegerField()
    end_frame_index = models.IntegerField()
    start_frame = models.ForeignKey(Frame, null=True, related_name="start_frame")
    end_frame = models.ForeignKey(Frame, null=True, related_name="end_frame")
    start_region = models.ForeignKey(Region, null=True, related_name="start_region")
    end_region = models.ForeignKey(Region, null=True, related_name="end_region")
    text = models.TextField(default="")
    metadata = JSONField(blank=True, null=True)
    event = models.ForeignKey(TEvent)


class RegionRelation(models.Model):
    """
    Captures relations between Regions within a video/dataset.
    """
    video = models.ForeignKey(Video)
    source_region = models.ForeignKey(Region, related_name='source_region')
    target_region = models.ForeignKey(Region, related_name='target_region')
    event = models.ForeignKey(TEvent)
    name = models.CharField(max_length=400)
    weight = models.FloatField(null=True)
    metadata = JSONField(blank=True, null=True)


class HyperRegionRelation(models.Model):
    """
    Captures relations between a Region in a video/dataset and an external globally addressed path / URL.
    HyperRegionRelation is an equivalent of anchor tags / hyperlinks.
    e.g. Region -> http://http://akshaybhat.com/static/img/akshay.jpg
    """
    video = models.ForeignKey(Video)
    region = models.ForeignKey(Region)
    event = models.ForeignKey(TEvent)
    name = models.CharField(max_length=400)
    weight = models.FloatField(null=True)
    metadata = JSONField(blank=True, null=True)
    path = models.TextField()
    full_frame = models.BooleanField(default=False)
    x = models.IntegerField(default=0)
    y = models.IntegerField(default=0)
    h = models.IntegerField(default=0)
    w = models.IntegerField(default=0)
    # Unlike region frame_index is only required if the path points to a video or a .gif
    frame_index = models.IntegerField(null=True)
    segment_index = models.IntegerField(null=True)


class HyperTubeRegionRelation(models.Model):
    """
    Captures relations between a Tube in a video/dataset and an external globally addressed path / URL.
    HyperTubeRegionRelation is an equivalent of anchor tags / hyperlinks.
    e.g. Tube -> http://http://akshaybhat.com/static/img/akshay.jpg
    """
    video = models.ForeignKey(Video)
    tube = models.ForeignKey(Tube)
    event = models.ForeignKey(TEvent)
    name = models.CharField(max_length=400)
    weight = models.FloatField(null=True)
    metadata = JSONField(blank=True, null=True)
    path = models.TextField()
    full_frame = models.BooleanField(default=False)
    x = models.IntegerField(default=0)
    y = models.IntegerField(default=0)
    h = models.IntegerField(default=0)
    w = models.IntegerField(default=0)
    # Unlike region frame_index is only required if the path points to a video or a .gif
    frame_index = models.IntegerField(null=True)
    segment_index = models.IntegerField(null=True)


class TubeRelation(models.Model):
    """
    Captures relations between Tubes within a video/dataset.
    """
    video = models.ForeignKey(Video)
    source_tube = models.ForeignKey(Tube, related_name='source_tube')
    target_tube = models.ForeignKey(Tube, related_name='target_tube')
    event = models.ForeignKey(TEvent)
    name = models.CharField(max_length=400)
    weight = models.FloatField(null=True)
    metadata = JSONField(blank=True, null=True)


class TubeRegionRelation(models.Model):
    """
    Captures relations between Tube and Region within a video/dataset.
    """
    video = models.ForeignKey(Video)
    tube = models.ForeignKey(Tube)
    region = models.ForeignKey(Region)
    event = models.ForeignKey(TEvent)
    name = models.CharField(max_length=400)
    weight = models.FloatField(null=True)
    metadata = JSONField(blank=True, null=True)


class DeletedVideo(models.Model):
    deleter = models.ForeignKey(User, related_name="user_deleter", null=True)
    video_uuid = models.UUIDField(default=uuid.uuid4, null=True)
    created = models.DateTimeField('date created', auto_now_add=True)

    def __unicode__(self):
        return u'Deleted {} by {}'.format(self.video_uuid, self.deleter)


class ManagementAction(models.Model):
    parent_task = models.CharField(max_length=500, default="")
    op = models.CharField(max_length=500, default="")
    host = models.CharField(max_length=500, default="")
    message = models.TextField()
    created = models.DateTimeField('date created', auto_now_add=True)
    ping_index = models.IntegerField(null=True)


class SystemState(models.Model):
    created = models.DateTimeField('date created', auto_now_add=True)
    process_stats = JSONField(blank=True, null=True)
    worker_stats = JSONField(blank=True, null=True)
    redis_stats = JSONField(blank=True, null=True)
    queues = JSONField(blank=True, null=True)
    hosts = JSONField(blank=True, null=True)


class QueryRegionIndexVector(models.Model):
    event = models.ForeignKey(TEvent)
    query_region = models.ForeignKey(QueryRegion)
    vector = models.BinaryField()
    created = models.DateTimeField('date created', auto_now_add=True)


class Export(models.Model):
    MODEL_EXPORT = constants.MODEL_EXPORT
    VIDEO_EXPORT = constants.VIDEO_EXPORT
    EXPORT_TYPES = (
        (MODEL_EXPORT, 'Model export'),
        (VIDEO_EXPORT, 'Video export'),
    )
    export_type = models.CharField(max_length=1, choices=EXPORT_TYPES, db_index=True)
    event = models.ForeignKey(TEvent)
    url = models.TextField(default="")
    created = models.DateTimeField('date created', auto_now_add=True)


class TaskRestart(models.Model):
    original_event_pk = models.IntegerField(null=False)
    launched_event_pk = models.IntegerField()
    attempts = models.IntegerField(default=0)
    arguments = JSONField(blank=True, null=True)
    operation = models.CharField(max_length=100, default="")
    queue = models.CharField(max_length=100, default="")
    video_uuid = models.UUIDField(default=uuid.uuid4, null=True)
    process = models.ForeignKey(DVAPQL)
    created = models.DateTimeField('date created', auto_now_add=True)
